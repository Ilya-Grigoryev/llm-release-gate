import json
import threading
import time
from dataclasses import replace
from pathlib import Path

import openai
import pytest

from llm_release_gate.golden import load_cases
from llm_release_gate.pipeline import Answer, PipelineConfig, Retryable, config_hash
from llm_release_gate.pipelines.sroie import build
from llm_release_gate.runner import read_records, run

FIXTURES = Path(__file__).parent / "fixtures"
[SYNTH] = load_cases(FIXTURES / "golden")
CASES = [replace(SYNTH, id=f"synth-00{i}") for i in (1, 2, 3)]
HASHES = {"config_hash": "c" * 64, "set_hash": "s" * 64}


def score(case, answer):
    return {f: answer.output.get(f) == v for f, v in case.expected.items()}


class Crash(BaseException):
    """Stands in for the process being killed."""


class Replay:
    """A recorded provider: replays model answers from a fixture, in order, per case."""

    def __init__(self, fail=None, delay=0.0):
        lines = (FIXTURES / "replay" / "synth-001.jsonl").read_text().splitlines()
        self.answers = [Answer(**json.loads(line)) for line in lines]
        self.calls = []
        self.fail = fail or (lambda case, n: None)
        self.delay = delay
        self.lock = threading.Lock()
        self.active = self.peak = 0

    def run(self, case):
        with self.lock:
            n = sum(c == case.id for c in self.calls)
            self.calls.append(case.id)
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            time.sleep(self.delay)
            self.fail(case, len(self.calls))
            return self.answers[n % len(self.answers)]
        finally:
            with self.lock:
                self.active -= 1


def go(pipeline, out, **kwargs):
    kwargs = {"score": score, "sleep": lambda s: None, **HASHES, **kwargs}
    return run(pipeline, CASES, 4, out, **kwargs)


def test_one_record_per_case_and_repetition(tmp_path):
    out = tmp_path / "runs.jsonl"
    assert go(Replay(), out) == 12
    records = read_records(out)
    assert sorted((r["case"], r["rep"]) for r in records) == [
        (c.id, k) for c in CASES for k in range(4)
    ]
    r = records[0]
    assert r["config_hash"] == "c" * 64 and r["set_hash"] == "s" * 64
    assert r["model"] == "gpt-4.1-mini-2025-04-14" and r["fingerprint"] == "fp_replay"
    assert r["raw"] and r["output"] and r["input_tokens"] == 120
    assert r["retries"] == 0 and r["error"] is None and r["run_id"]
    assert r["timestamp"].endswith("+00:00")
    # the fixture answers wrong on `total` once in four repetitions
    assert sum(not r["hits"]["total"] for r in records) == 3
    assert {r["score"] for r in records} == {1.0, 0.75}


def test_resume_after_a_crash_runs_only_the_rest(tmp_path):
    out = tmp_path / "runs.jsonl"

    def crash_on_fifth(case, n):
        if n == 5:
            raise Crash

    first = Replay(fail=crash_on_fifth, delay=0.02)
    with pytest.raises(Crash):
        go(first, out, workers=1)
    # Queued calls are dropped, not paid for; only the one already running finishes.
    assert len(first.calls) <= 6
    assert len(read_records(out)) == 4
    second = Replay()
    assert go(second, out) == 8
    assert len(second.calls) == 8
    assert len({(r["case"], r["rep"]) for r in read_records(out)}) == 12
    assert go(Replay(), out) == 0


def test_a_line_cut_off_by_a_crash_is_ignored(tmp_path):
    out = tmp_path / "runs.jsonl"
    go(Replay(), out)
    with out.open("a") as f:
        f.write('{"config_hash": "cc')
    assert len(read_records(out)) == 12
    assert go(Replay(), out) == 0


def test_another_config_or_set_is_not_reused(tmp_path):
    out = tmp_path / "runs.jsonl"
    go(Replay(), out)
    assert go(Replay(), out, config_hash="d" * 64) == 12
    assert go(Replay(), out, set_hash="t" * 64) == 12


def test_rate_limits_back_off_and_count_retries(tmp_path):
    out = tmp_path / "runs.jsonl"
    waits = []

    def two_rate_limits(case, n):
        if n <= 2:
            raise Retryable("429")

    go(Replay(fail=two_rate_limits), out, workers=1, sleep=waits.append)
    assert waits == [1, 2]
    assert max(r["retries"] for r in read_records(out)) == 2


def test_errors_are_recorded_and_retried_on_the_next_run(tmp_path):
    out = tmp_path / "runs.jsonl"

    def broken(case, n):
        if case.id == "synth-002":
            raise ValueError("bad input")
        if case.id == "synth-003":
            raise Retryable("timeout")

    go(Replay(fail=broken), out, max_retries=2)
    errors = {r["case"]: r for r in read_records(out) if r["error"]}
    assert len(errors) == 2 and len(read_records(out)) == 12
    assert errors["synth-002"]["error"] == "ValueError: bad input"
    assert errors["synth-003"]["retries"] == 2
    assert errors["synth-003"]["output"] is None and errors["synth-003"]["hits"] is None
    assert go(Replay(), out) == 8


def test_workers_run_in_parallel_up_to_the_limit(tmp_path):
    pipeline = Replay(delay=0.05)
    go(pipeline, tmp_path / "runs.jsonl", workers=3)
    assert pipeline.peak == 3


def test_config_hash_follows_the_prompt_text(tmp_path):
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Extract fields.")
    config = PipelineConfig(
        "sroie", "gpt-4.1-mini-2025-04-14", prompt, "text", {"seed": 0}
    )
    before = config_hash(config)
    assert config_hash(replace(config, params={"seed": 0})) == before
    prompt.write_text("Extract the fields.")
    assert config_hash(config) != before


def test_sroie_rate_limit_becomes_retryable(tmp_path):
    def rate_limited(**request):
        # Built without an HTTP response: only the class matters to the pipeline.
        error = openai.RateLimitError.__new__(openai.RateLimitError)
        Exception.__init__(error, "slow down")
        raise error

    client = type("C", (), {})()
    client.chat = type("Chat", (), {})()
    client.chat.completions = type(
        "Completions", (), {"create": staticmethod(rate_limited)}
    )
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Extract fields.")
    config = PipelineConfig("sroie", "gpt-4.1-mini-2025-04-14", prompt, "text")
    with pytest.raises(Retryable):
        build(config, client).run(SYNTH)
