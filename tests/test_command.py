import json
import os
import time
from pathlib import Path

import pytest

from llm_release_gate import runner, trace
from llm_release_gate.golden import load_cases, validate
from llm_release_gate.metrics import hits
from llm_release_gate.pipeline import (
    Fatal,
    Retryable,
    config_hash,
    load_config,
    load_pipeline,
)
from llm_release_gate.runner import read_records

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN = FIXTURES / "golden"
AGENT = FIXTURES / "command" / "agent.sh"
WRAPPER = FIXTURES / "command" / "wrapper.sh"


def config(tmp_path, mode="answer", timeout=10, command=None):
    path = tmp_path / "command.yaml"
    path.write_text(
        "pipeline: command\n"
        f"command: {json.dumps(command or ['sh', str(AGENT)])}\n"
        "model: fake-model-2026-01-01\n"
        f"prompt: {FIXTURES / 'prompt.md'}\n"
        "input: text\n"
        f"params: {{mode: {mode}}}\n"
        f"timeout_s: {timeout}\n"
    )
    return load_config(path)


def run_case(cfg):
    [case] = load_cases(GOLDEN)
    return load_pipeline(cfg).run(case)


def traced(cfg):
    """Run one case inside a trace, as the runner does; returns the trace and the error, if any."""
    t, error = trace.Trace(), None
    with trace.active(t):
        try:
            run_case(cfg)
        except Exception as e:  # noqa: BLE001
            error = e
    return t, error


def test_a_program_answers_and_the_record_keeps_its_trace(tmp_path):
    set_hash, _ = validate(GOLDEN)
    out = tmp_path / "runs.jsonl"
    runner.run(
        load_pipeline(config(tmp_path)),
        load_cases(GOLDEN),
        1,
        out,
        config_hash="c" * 64,
        set_hash=set_hash,
        score=hits,
        workers=1,
    )
    [r] = read_records(out)
    assert (
        r["error"] is None and r["score"] == 1.0 and r["raw"] == "answered by agent.sh"
    )
    assert [s["kind"] for s in r["trace"]["steps"]] == ["llm", "tool"]
    assert (
        r["trace"]["final_state"] == {"done": True}
        and r["usage"]["agent"]["tokens_in"] == 12
    )


def test_the_program_gets_the_case_and_the_version_but_not_the_expected_values(
    tmp_path,
):
    spy = tmp_path / "spy.sh"
    spy.write_text(
        f"#!/bin/sh\ncat > {tmp_path / 'request.json'}\necho '{{\"output\": null}}'\n"
    )
    run_case(config(tmp_path, command=["sh", str(spy)]))
    request = json.loads((tmp_path / "request.json").read_text())
    assert request["case"]["id"] == "synth-001"
    assert all(
        Path(p).is_absolute() and Path(p).exists()
        for p in request["case"]["inputs"].values()
    )
    assert request["config"]["model"] == "fake-model-2026-01-01" and request["config"][
        "params"
    ] == {"mode": "answer"}
    [case] = load_cases(GOLDEN)
    sent = json.dumps(request)
    assert "expected" not in sent
    assert not [v for v in case.expected.values() if str(v) in sent]


@pytest.mark.parametrize(
    "mode, error, match",
    [
        ("retry", Retryable, "rate limited"),
        ("stop", Fatal, "exit 78: no quota"),
        ("notfound", Fatal, "exit 127: sh: agent: not found"),
        ("fail", RuntimeError, "exit 3: agent crashed"),
        ("garbage", ValueError, "not JSON"),
        ("list", TypeError, "must be a JSON object"),
        ("nooutput", TypeError, "`output` must be an object or null"),
        ("textoutput", TypeError, "`output` must be an object or null"),
        ("numbermodel", TypeError, "model must be a string"),
        ("negtokens", ValueError, "input_tokens must be a whole number"),
        ("floattokens", ValueError, "output_tokens must be a whole number"),
    ],
)
def test_exit_codes_map_to_retry_stop_or_a_failed_run(tmp_path, mode, error, match):
    with pytest.raises(error, match=match):
        run_case(config(tmp_path, mode))


@pytest.mark.parametrize(
    "mode, stop", [("retry", None), ("stop", None), ("fail", "error")]
)
def test_a_failed_exit_keeps_the_steps_the_program_paid_for(tmp_path, mode, stop):
    t, error = traced(config(tmp_path, mode))
    assert error is not None
    assert [(s["kind"], s["tokens_in"]) for s in t.steps] == [
        ("llm", 12)
    ] and t.stop == stop


def test_a_broken_trace_after_a_failed_exit_leaves_a_note_and_keeps_the_exit_error(
    tmp_path,
):
    t, error = traced(config(tmp_path, "failbadtrace"))
    assert isinstance(error, RuntimeError) and "exit 3" in str(error)
    assert t.steps == [] and "actor" in t.notes[0]


def test_a_slow_program_is_retried(tmp_path):
    start = time.perf_counter()
    with pytest.raises(Retryable, match="no answer within 1 s"):
        run_case(config(tmp_path, "slow", timeout=1))
    assert time.perf_counter() - start < 4  # its `sleep 5` was killed too


def test_a_timeout_kills_what_the_program_started(tmp_path):
    pid_file = tmp_path / "child.pid"
    with pytest.raises(Retryable):
        run_case(
            config(tmp_path, timeout=1, command=["sh", str(WRAPPER), str(pid_file)])
        )
    child = int(pid_file.read_text())
    for _ in range(100):  # the orphan is reaped by init shortly after the kill
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)
    pytest.fail(f"child {child} still runs")


def test_a_missing_program_stops_the_run(tmp_path):
    with pytest.raises(Fatal, match="cannot start"):
        run_case(config(tmp_path, command=["/no/such/program"]))


def test_a_program_that_is_not_executable_stops_the_run(tmp_path):
    script = tmp_path / "agent.sh"
    script.write_text(AGENT.read_text())
    script.chmod(0o644)
    with pytest.raises(Fatal, match="cannot start"):
        run_case(config(tmp_path, command=[str(script)]))


def test_bytes_that_are_not_utf8_do_not_lose_the_answer(tmp_path):
    answer = run_case(config(tmp_path, "latin1"))
    assert answer.output == {"note": "caf\ufffd"}


def test_a_bare_answer_reports_no_model_and_raw_is_the_output(tmp_path):
    answer = run_case(config(tmp_path, "bare"))
    assert answer.model is None  # not the configured one: the program did not report it
    assert answer.raw == '{"total": "12.50"}'
    assert (answer.input_tokens, answer.output_tokens) == (0, 0)


def test_model_null_stays_none_and_raw_that_is_not_text_is_json(tmp_path):
    assert run_case(config(tmp_path, "nullmodel")).model is None
    assert run_case(config(tmp_path, "rawobject")).raw == '{"text": "hi"}'


@pytest.mark.parametrize(
    "mode, error, match",
    [
        ("badstop", TypeError, "stop must be a string"),
        ("badts", ValueError, "ts must be a string"),
    ],
)
def test_trace_fields_of_the_wrong_type_fail_the_run(tmp_path, mode, error, match):
    _, e = traced(config(tmp_path, mode))
    assert isinstance(e, error) and match in str(e)


def test_the_runner_numbers_the_programs_steps(tmp_path):
    t, error = traced(config(tmp_path, "renumber"))
    assert error is None
    [s] = t.steps
    assert (s["seq"], s["run_attempt"], s["self"]) == (0, 0, 1)


def test_a_step_that_breaks_the_format_fails_the_run(tmp_path):
    set_hash, _ = validate(GOLDEN)
    out = tmp_path / "runs.jsonl"
    runner.run(
        load_pipeline(config(tmp_path, "badstep")),
        load_cases(GOLDEN),
        1,
        out,
        config_hash="c" * 64,
        set_hash=set_hash,
        score=hits,
        workers=1,
    )
    [r] = read_records(out)
    assert "actor" in r["error"]


def test_the_command_is_part_of_the_version(tmp_path):
    a = config(tmp_path)
    b = config(tmp_path, command=["sh", str(AGENT), "--fast"])
    assert config_hash(a) != config_hash(b)


def test_configs_without_a_command_keep_their_hash():
    from dataclasses import asdict

    from llm_release_gate.hashing import canonical_hash, file_hash
    from llm_release_gate.pipeline import pipeline_module

    cfg = load_config(FIXTURES / "config.yaml")
    old = {
        k: v for k, v in asdict(cfg).items() if k != "command"
    }  # the fields before `command` existed
    old.update(
        prompt=file_hash(cfg.prompt),
        pipeline_version=getattr(pipeline_module(cfg.pipeline), "VERSION", None),
    )
    assert config_hash(cfg) == canonical_hash(old)


@pytest.mark.parametrize(
    "extra, match",
    [
        ("pipeline: command\n", "goes with"),
        ("pipeline: replay_pipeline\ncommand: [sh, x.sh]\n", "goes with"),
        ("pipeline: command\ncommand: sh x.sh\n", "must be a list"),
    ],
)
def test_bad_command_configs_are_refused(tmp_path, extra, match):
    path = tmp_path / "c.yaml"
    path.write_text(extra + "model: m-2026-01-01\nprompt: p.md\ninput: text\n")
    with pytest.raises(ValueError, match=match):
        load_config(path)
