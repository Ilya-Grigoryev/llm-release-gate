import json
from pathlib import Path

import pytest

from llm_release_gate import runner
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
    assert "expected" not in json.dumps(request)


@pytest.mark.parametrize(
    "mode, error, match",
    [
        ("retry", Retryable, "rate limited"),
        ("stop", Fatal, "no quota"),
        ("fail", RuntimeError, "exit 3: agent crashed"),
        ("garbage", ValueError, "not JSON"),
    ],
)
def test_exit_codes_map_to_retry_stop_or_a_failed_run(tmp_path, mode, error, match):
    with pytest.raises(error, match=match):
        run_case(config(tmp_path, mode))


def test_a_slow_program_is_retried(tmp_path):
    with pytest.raises(Retryable, match="no answer within 1 s"):
        run_case(config(tmp_path, "slow", timeout=1))


def test_a_missing_program_stops_the_run(tmp_path):
    with pytest.raises(Fatal, match="cannot start"):
        run_case(config(tmp_path, command=["/no/such/program"]))


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
