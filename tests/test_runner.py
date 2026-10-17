import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import openai
import pytest

from llm_release_gate import runner
from llm_release_gate.golden import load_cases
from llm_release_gate.pipeline import (
    Answer,
    Fatal,
    PipelineConfig,
    Retryable,
    config_hash,
    load_config,
)
from llm_release_gate.pipelines.sroie import build
from llm_release_gate.runner import read_records, results, run

FIXTURES = Path(__file__).parent / "fixtures"
[SYNTH] = load_cases(FIXTURES / "golden")
CASES = [replace(SYNTH, id=f"synth-00{i}") for i in (1, 2, 3)]
HASHES = {"config_hash": "c" * 64, "set_hash": "s" * 64}


def score(case, answer):
    output = answer.output or {}
    return {f: output.get(f) == v for f, v in case.expected.items()}


class Crash(BaseException):
    """Stands in for the process being killed."""


class Replay:
    """A recorded provider: replays model answers from a fixture, in order, per case."""

    def __init__(self, fail=None, delay=0.0, answers=None):
        lines = (FIXTURES / "replay" / "synth-001.jsonl").read_text().splitlines()
        self.answers = answers or [Answer(**json.loads(line)) for line in lines]
        self.calls = []
        self.fail = fail or (lambda case, n: None)
        self.delay = delay
        self.lock = threading.Lock()
        self.active = self.peak = 0

    def run(self, case):
        with self.lock:
            n = sum(c == case.id for c in self.calls)
            self.calls.append(case.id)
            number = len(self.calls)
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            time.sleep(self.delay)
            self.fail(case, number)
            return self.answers[n % len(self.answers)]
        finally:
            with self.lock:
                self.active -= 1


def go(pipeline, out, **kwargs):
    kwargs = {"score": score, "wait": lambda s: False, **HASHES, **kwargs}
    return run(pipeline, CASES, 4, out, **kwargs)


def test_one_record_per_case_and_repetition(tmp_path):
    out = tmp_path / "runs.jsonl"
    assert go(Replay(), out) == 12
    records = read_records(out)
    assert sorted((r["case"], r["rep"]) for r in records) == [
        (c.id, k) for c in CASES for k in range(4)
    ]
    r = records[0]
    assert r["record_version"] == 1
    assert r["config_hash"] == "c" * 64 and r["set_hash"] == "s" * 64
    assert r["model"] == "gpt-4.1-mini-2025-04-14" and r["fingerprint"] == "fp_replay"
    assert r["raw"] and r["output"] and r["input_tokens"] == 120
    assert r["retries"] == 0 and r["error"] is None and r["run_id"]
    assert r["timestamp"].endswith("+00:00")
    # the fixture answers wrong on `total` once in four repetitions
    assert sum(not r["hits"]["total"] for r in records) == 3
    assert {r["score"] for r in records} == {1.0, 0.75}


def test_resume_after_a_crash_keeps_finished_calls_and_runs_the_rest(tmp_path):
    out = tmp_path / "runs.jsonl"

    def crash_on_fifth(case, n):
        if n == 5:
            raise Crash

    first = Replay(fail=crash_on_fifth, delay=0.02)
    with pytest.raises(Crash):
        go(first, out, workers=1)
    # queued calls are dropped; every call that finished is written
    assert len(first.calls) <= 6
    saved = len(read_records(out))
    assert saved == len(first.calls) - 1
    second = Replay()
    assert go(second, out) == 12 - saved
    assert len(second.calls) == 12 - saved
    assert len(results(out, **HASHES)) == 12
    assert go(Replay(), out) == 0


def test_fatal_stops_the_run_and_keeps_paid_answers(tmp_path):
    out = tmp_path / "runs.jsonl"

    def out_of_quota(case, n):
        if n == 3:
            raise Fatal("insufficient_quota")

    pipeline = Replay(fail=out_of_quota, delay=0.02)
    with pytest.raises(Fatal):
        go(pipeline, out, workers=2)
    records = read_records(out)
    # every paid answer is written; the queue is dropped, though each of the two
    # workers may have taken one more call before the stop
    assert len(records) == len(pipeline.calls) - 1 and len(pipeline.calls) <= 6
    assert all(r["error"] is None for r in records)


def test_stop_cuts_a_running_backoff_short(tmp_path):
    def stuck_then_fatal(case, n):
        if case.id == "synth-001":
            time.sleep(0.1)
            raise Fatal("stop")
        raise Retryable("429")

    out = tmp_path / "runs.jsonl"
    start = time.monotonic()
    with pytest.raises(Fatal):
        run(
            Replay(fail=stuck_then_fatal),
            CASES,
            1,
            out,
            score=score,
            workers=3,
            **HASHES,
        )
    # without the stop the backoff would wait 1 + 2 + 4 + 8 + 16 s
    assert time.monotonic() - start < 3


def test_append_after_a_cut_off_line_starts_a_new_line(tmp_path):
    out = tmp_path / "runs.jsonl"
    out.write_text('{"config_hash": "cc')
    assert go(Replay(), out) == 12
    assert len(read_records(out)) == 12
    assert go(Replay(), out) == 0


def test_foreign_lines_are_ignored(tmp_path):
    out = tmp_path / "runs.jsonl"
    out.write_text('{"case": "old format"}\n[1, 2]\n')
    assert go(Replay(), out) == 12


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

    go(Replay(fail=two_rate_limits), out, workers=1, wait=waits.append)
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
    assert len(results(out, **HASHES)) == 12


def test_a_failing_scorer_keeps_the_answer(tmp_path):
    out = tmp_path / "runs.jsonl"

    def picky(case, answer):
        if case.id == "synth-002":
            raise KeyError("company")
        return score(case, answer)

    assert go(Replay(), out, score=picky) == 12
    bad = [r for r in read_records(out) if r["score_error"]]
    assert len(bad) == 4
    assert bad[0]["score_error"] == "KeyError: 'company'" and bad[0]["raw"]
    assert bad[0]["error"] is None and bad[0]["hits"] is None
    # the answer is paid for: a rerun does not call the model again
    assert go(Replay(), out, score=picky) == 0


def test_an_unparsed_answer_is_still_scored(tmp_path):
    out = tmp_path / "runs.jsonl"
    garbled = Answer(None, '{"company": "TE', 120, 300, 1.0, "m-2025-01-01")
    go(Replay(answers=[garbled]), out)
    r = read_records(out)[0]
    assert r["hits"] == {f: False for f in SYNTH.expected} and r["score"] == 0


def test_workers_run_in_parallel_up_to_the_limit(tmp_path):
    pipeline = Replay(delay=0.05)
    go(pipeline, tmp_path / "runs.jsonl", workers=3)
    assert pipeline.peak == 3


def test_config_hash_follows_prompt_text_and_retry_policy(tmp_path):
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Extract fields.")
    config = PipelineConfig(
        "sroie", "gpt-4.1-mini-2025-04-14", prompt, "text", {"seed": 0}
    )
    before = config_hash(config)
    assert config_hash(replace(config, params={"seed": 0})) == before
    assert config_hash(replace(config, timeout_s=30)) != before
    prompt.write_text("Extract the fields.")
    assert config_hash(config) != before


def test_load_config_reads_the_retry_policy(tmp_path):
    (tmp_path / "c.yaml").write_text(
        "pipeline: sroie\nmodel: gpt-4.1-mini-2025-04-14\nprompt: p.md\ninput: text\n"
        "max_retries: 2\ntimeout_s: 30\n"
    )
    config = load_config(tmp_path / "c.yaml")
    assert (config.max_retries, config.timeout_s) == (2, 30)


def rate_limit(code=None):
    # Built without an HTTP response: only the class and the code matter to the pipeline.
    error = openai.RateLimitError.__new__(openai.RateLimitError)
    Exception.__init__(error, "slow down")
    error.code = code
    return error


@pytest.mark.parametrize(
    "code, expected", [(None, Retryable), ("insufficient_quota", Fatal)]
)
def test_sroie_maps_rate_limits(tmp_path, code, expected):
    def create(**request):
        raise rate_limit(code)

    client = type("Client", (), {})()
    client.chat = type("Chat", (), {})()
    client.chat.completions = type("Completions", (), {"create": staticmethod(create)})
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Extract fields.")
    config = PipelineConfig("sroie", "gpt-4.1-mini-2025-04-14", prompt, "text")
    with pytest.raises(expected):
        build(config, client).run(SYNTH)


@pytest.mark.parametrize(
    "extra",
    [
        "max_retries: '5'\n",
        "max_retries: -1\n",
        "timeout_s: null\n",
        "timeout_s: 0\n",
        "timeout_s: .nan\n",
        "timeout_s: .inf\n",
    ],
)
def test_load_config_rejects_a_bad_retry_policy(tmp_path, extra):
    (tmp_path / "c.yaml").write_text(
        "pipeline: sroie\nmodel: gpt-4.1-mini-2025-04-14\nprompt: p.md\ninput: text\n"
        + extra
    )
    with pytest.raises(ValueError):
        load_config(tmp_path / "c.yaml")


def test_timeout_written_as_int_or_float_hashes_alike(tmp_path):
    base = (
        "pipeline: sroie\nmodel: gpt-4.1-mini-2025-04-14\nprompt: p.md\ninput: text\n"
    )
    (tmp_path / "p.md").write_text("Extract fields.")
    (tmp_path / "a.yaml").write_text(base + "timeout_s: 60\n")
    (tmp_path / "b.yaml").write_text(base + "timeout_s: 60.0\n")
    a, b = load_config(tmp_path / "a.yaml"), load_config(tmp_path / "b.yaml")
    assert config_hash(a) == config_hash(b)


def test_a_stopped_backoff_is_marked(tmp_path):
    out = tmp_path / "runs.jsonl"
    go(Replay(fail=lambda case, n: (_ for _ in ()).throw(Retryable("429"))), out,
       wait=lambda s: True)  # fmt: skip
    assert {r["error"] for r in read_records(out)} == {
        "stopped during backoff: Retryable: 429"
    }


def test_an_interrupt_while_scoring_keeps_the_answer(tmp_path):
    out = tmp_path / "runs.jsonl"
    interrupted = []

    def interrupt_once(case, answer):
        if case.id == "synth-002" and not interrupted:
            interrupted.append(case.id)
            raise Crash
        return score(case, answer)

    first = Replay(delay=0.02)
    with pytest.raises(Crash):
        go(first, out, workers=1, score=interrupt_once)
    # the answer being scored when Ctrl-C came is written with the others
    saved = len(read_records(out))
    assert saved == len(first.calls) and "synth-002" in {
        r["case"] for r in read_records(out)
    }
    second = Replay()
    assert go(second, out) == 12 - saved and len(second.calls) == 12 - saved


def test_an_unscored_field_keeps_the_answer(tmp_path):
    out = tmp_path / "runs.jsonl"

    def partial(case, answer):
        return {**score(case, answer), "total": None}

    assert go(Replay(), out, score=partial) == 12
    for r in read_records(out):
        # the score is the share of right fields among the scored ones
        assert r["hits"]["total"] is None and r["score"] == 1.0
        assert r["score_error"] is None and r["error"] is None
    assert go(Replay(), out, score=partial) == 0


def test_an_unserializable_answer_is_recorded_and_the_rest_written(tmp_path):
    class Odd(Replay):
        def run(self, case):
            answer = super().run(case)
            if case.id == "synth-002":
                return replace(answer, output={"total": object()})
            return answer

    out = tmp_path / "runs.jsonl"
    assert go(Odd(), out) == 12
    bad = [r for r in read_records(out) if r["error"]]
    assert len(bad) == 4 and bad[0]["error"].startswith("record not serializable")
    assert bad[0]["raw"]
    assert go(Replay(), out) == 4


@pytest.mark.parametrize("max_retries", ["5", -1, True, 2.0])
def test_run_rejects_a_bad_max_retries(tmp_path, max_retries):
    with pytest.raises(ValueError):
        go(Replay(), tmp_path / "runs.jsonl", max_retries=max_retries)


def test_an_interrupt_while_queueing_keeps_paid_answers(tmp_path, monkeypatch):
    class Interrupting(ThreadPoolExecutor):
        submitted = 0

        def submit(self, *args, **kwargs):
            Interrupting.submitted += 1
            if Interrupting.submitted == 6:
                raise Crash
            return super().submit(*args, **kwargs)

    monkeypatch.setattr(runner, "ThreadPoolExecutor", Interrupting)
    out = tmp_path / "runs.jsonl"
    pipeline = Replay(delay=0.02)
    with pytest.raises(Crash):
        go(pipeline, out, workers=1)
    # the queue is dropped and every call that ran is written
    assert len(read_records(out)) == len(pipeline.calls) <= 2
