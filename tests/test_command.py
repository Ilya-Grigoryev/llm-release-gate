import json
import subprocess
import time
from pathlib import Path

import pytest

from llm_release_gate import command, protocol, runner, trace
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
    assert (r["input_tokens"], r["output_tokens"], r["model"]) == (
        12,
        3,
        "fake-model-2026-01-01",
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
    assert protocol.errors(request, "request") == [] and request["protocol"] == 1
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
        ("silentstop", Fatal, "^exit 78$"),
        ("notfound", Fatal, "exit 127: sh: agent: not found"),
        ("fail", RuntimeError, "exit 3: agent crashed"),
        ("garbage", ValueError, "not JSON"),
        ("list", TypeError, "must be a JSON object"),
        ("nooutput", ValueError, "answer: missing output"),
        ("textoutput", ValueError, "output: '12.50' is not of type 'object', 'null'"),
        ("numbermodel", ValueError, "model: 4 is not of type 'string', 'null'"),
        ("negtokens", ValueError, "input_tokens: -1 is less than the minimum of 0"),
        ("floattokens", ValueError, "output_tokens: 2.5 is not of type 'integer'"),
        ("otherprotocol", Fatal, "answer speaks protocol 2, the gate 1"),
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


def test_a_broken_step_fails_the_run_and_the_steps_before_it_stay(tmp_path):
    t, error = traced(config(tmp_path, "halfbroken"))
    assert isinstance(error, ValueError) and "trace.steps.1" in str(error)
    assert [(s["kind"], s["tokens_in"]) for s in t.steps] == [("llm", 12)]


def test_a_broken_trace_after_a_failed_exit_leaves_a_note_and_keeps_the_exit_error(
    tmp_path,
):
    t, error = traced(config(tmp_path, "failbadtrace"))
    assert isinstance(error, RuntimeError) and "exit 3" in str(error)
    assert t.steps == [] and "actor" in t.notes[0]


def test_a_slow_program_is_retried(tmp_path):
    with pytest.raises(Retryable, match="no answer within 1 s"):
        run_case(config(tmp_path, "slow", timeout=1))


def test_an_interrupt_kills_the_program(tmp_path, monkeypatch):
    killed, kill = [], command.kill

    def interrupted(self, *args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(command.subprocess.Popen, "communicate", interrupted)
    monkeypatch.setattr(command, "kill", lambda p: (killed.append(p.pid), kill(p)))
    with pytest.raises(KeyboardInterrupt):
        run_case(config(tmp_path, "slow"))
    assert killed


def gone(pid):
    """Dead, or a zombie waiting for init (a container may have no init to reap it)."""
    ps = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)],
        capture_output=True,
        text=True,
        check=False,
    )
    return ps.stdout.strip()[:1] in ("", "Z")


def test_a_timeout_kills_what_the_program_started(tmp_path):
    pid_file = tmp_path / "child.pid"
    with pytest.raises(Retryable):
        run_case(
            config(tmp_path, timeout=1, command=["sh", str(WRAPPER), str(pid_file)])
        )
    child = int(pid_file.read_text())
    for _ in range(100):
        if gone(child):
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
        (
            "badstop",
            ValueError,
            "answer: trace.stop: 3 is not of type 'string', 'null'",
        ),
        (
            "badts",
            ValueError,
            "answer: trace.steps.0.ts: 5 is not of type 'string', 'null'",
        ),
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


def test_a_retry_does_not_keep_the_failed_attempts_state(tmp_path):
    t = trace.Trace()
    t.final_state, t.stop = {"half": True}, "error"  # left by a failed attempt
    with trace.active(t):
        run_case(config(tmp_path, "bare"))
    assert t.final_state is None and t.stop is None
