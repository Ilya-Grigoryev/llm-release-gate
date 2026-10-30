import json
from dataclasses import replace
from pathlib import Path

import pytest
from replay_pipeline import Replay
from scripted import ADDED, answer, failed, llm, program

from llm_release_gate import gate, metrics, runner, trace
from llm_release_gate.compare import load_arm
from llm_release_gate.golden import load_cases, validate
from llm_release_gate.metrics import hits
from llm_release_gate.pipeline import Fatal
from llm_release_gate.prices import usd
from llm_release_gate.runner import read_records

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN = FIXTURES / "golden"
PRICES = {"fake-model": (1.0, 2.0)}


def record_run(pipeline, out, cases=None, k=1, **kw):
    set_hash, _ = validate(GOLDEN)
    return runner.run(
        pipeline,
        cases or load_cases(GOLDEN),
        k,
        out,
        config_hash="c" * 64,
        set_hash=set_hash,
        score=hits,
        workers=kw.pop("workers", 1),
        **kw,
    )


# the format


def test_steps_follow_the_format_or_are_refused():
    t = trace.Trace()
    t.step("message", "agent", text="Hi")
    t.step("tool", "user", name="toggle_roaming", args={}, status="ok", result="on")
    with pytest.raises(ValueError, match="missing model"):
        t.step("llm", "agent", status="ok", tokens_in=1, tokens_out=1, cost_usd=None)
    with pytest.raises(ValueError, match="actor"):
        t.step("message", "robot", text="?")
    with pytest.raises(ValueError, match="status"):
        t.step("tool", "agent", name="x", args={}, status="maybe")
    assert [s["seq"] for s in t.steps] == [0, 1]
    assert all(s["run_attempt"] == 0 and s["ts"] for s in t.steps)


def test_a_failed_call_needs_no_model_or_tokens():
    t = trace.Trace()
    t.step("llm", "agent", status="error", error="RateLimitError", attempt=1)
    with pytest.raises(ValueError, match="missing attempt"):
        t.step("llm", "agent", status="error", error="RateLimitError")


def test_usage_splits_agent_and_simulator_and_counts_every_attempt():
    steps = [
        {
            "kind": "llm",
            "actor": "agent",
            "status": "ok",
            "model": "fake-model-1",
            "tokens_in": 100,
            "tokens_out": 10,
            "cost_usd": None,
            "run_attempt": 0,
        },
        {"kind": "llm", "actor": "agent", "status": "error", "run_attempt": 0},
        {
            "kind": "llm",
            "actor": "agent",
            "status": "ok",
            "model": "fake-model-1",
            "tokens_in": 100,
            "tokens_out": 10,
            "cost_usd": 0.5,
            "run_attempt": 1,
        },
        {
            "kind": "llm",
            "actor": "user",
            "status": "ok",
            "model": "other",
            "tokens_in": 10,
            "tokens_out": 1,
            "cost_usd": None,
            "run_attempt": 1,
        },
    ]
    u = trace.usage({"steps": steps}, PRICES)
    assert u["agent"] == {
        "llm_calls": 2,
        "tokens_in": 200,
        "tokens_out": 20,
        "cost_usd": pytest.approx(0.5 + 120e-6),
    }
    assert u["user"]["cost_usd"] is None  # no price for `other`
    assert [s["run_attempt"] for s in trace.last_attempt({"steps": steps})] == [1, 1]


# through the runner


def test_a_record_holds_the_programs_trace_and_its_usage(tmp_path):
    out = tmp_path / "runs.jsonl"
    record_run(program(tmp_path, {"synth-001": [{"answer": answer()}]}), out)
    [r] = read_records(out)
    assert (
        r["record_version"] == runner.RECORD_VERSION
        and r["error"] is None
        and r["wall_s"] >= 0
    )
    t = r["trace"]
    assert t["v"] == 1 and t["stop"] == "done" and t["final_state"] == {"balance": 5}
    assert [s["kind"] for s in t["steps"]] == ["llm", "tool", "llm"]
    assert [s["seq"] for s in t["steps"]] == [0, 1, 2]
    assert (
        r["usage"]["agent"]["llm_calls"] == 2
        and r["usage"]["agent"]["tokens_in"] == 230
    )
    assert "native" not in t and not (tmp_path / "runs.native.jsonl").exists()


def test_a_failed_run_keeps_the_steps_it_paid_for(tmp_path):
    out = tmp_path / "runs.jsonl"
    paid = answer([*ADDED[:2], failed()], stop="error")
    record_run(program(tmp_path, {"synth-001": [{"answer": paid, "exit": 3}]}), out)
    [r] = read_records(out)
    assert r["error"].startswith("RuntimeError: exit 3") and r["output"] is None
    assert [(s["kind"], s["status"]) for s in r["trace"]["steps"]] == [
        ("llm", "ok"),
        ("tool", "ok"),
        ("llm", "error"),
    ]
    assert r["usage"]["agent"]["llm_calls"] == 1


def test_a_retried_run_keeps_both_attempts_and_checks_see_the_last(tmp_path):
    out = tmp_path / "runs.jsonl"
    slow = answer([*ADDED[:2], failed()], stop="error")
    script = {"synth-001": [{"answer": slow, "exit": 75}, {"answer": answer()}]}
    record_run(program(tmp_path, script), out, wait=lambda s: False)
    [r] = read_records(out)
    assert r["error"] is None and r["retries"] == 1
    attempts = [s["run_attempt"] for s in r["trace"]["steps"]]
    assert attempts == [0, 0, 0, 1, 1, 1]  # llm, tool, failed llm; llm, tool, llm
    assert r["usage"]["agent"]["llm_calls"] == 3  # all paid
    assert len(trace.last_attempt(r["trace"])) == 3
    assert r["trace"]["final_state"] == {"balance": 5}


def test_a_fatal_error_keeps_the_partial_trace_and_stops(tmp_path):
    out = tmp_path / "runs.jsonl"
    broke = answer(ADDED[:2], stop="error")
    with pytest.raises(Fatal):
        record_run(
            program(tmp_path, {"synth-001": [{"answer": broke, "exit": 78}]}), out
        )
    [r] = read_records(out)
    assert r["error"].startswith("Fatal") and r["trace"]["stop"] == "error"
    assert r["usage"]["agent"]["llm_calls"] == 1  # the paid call is kept


def test_a_pipeline_without_a_trace_writes_the_record_as_before(tmp_path):
    out = tmp_path / "runs.jsonl"
    record_run(Replay(), out)
    [r] = read_records(out)
    assert r["trace"] is None and r["usage"] is None and r["score"] is not None
    assert not (tmp_path / "runs.native.jsonl").exists()


def test_parallel_runs_keep_their_own_traces(tmp_path):
    [case] = load_cases(GOLDEN)
    cases = [replace(case, id=f"c{i}") for i in range(8)]
    script = {c.id: [{"answer": answer()}] for c in cases}
    out = tmp_path / "runs.jsonl"
    record_run(program(tmp_path, script), out, cases=cases, k=2, workers=4)
    records = read_records(out)
    assert len(records) == 16
    assert all([s["seq"] for s in r["trace"]["steps"]] == [0, 1, 2] for r in records)


def test_the_user_simulators_calls_count_apart(tmp_path):
    steps = [llm("Hi, I was charged twice.", tokens=(40, 8), actor="user"), *ADDED]
    out = tmp_path / "runs.jsonl"
    record_run(program(tmp_path, {"synth-001": [{"answer": answer(steps)}]}), out)
    [r] = read_records(out)
    assert (
        r["usage"]["user"]["llm_calls"] == 1 and r["usage"]["agent"]["llm_calls"] == 2
    )


# old records and the gate's price


def test_a_version_2_record_still_reads_compares_and_costs(tmp_path):
    old = Path(__file__).parent / "fixtures" / "records" / "v2.jsonl"
    [r] = read_records(old)
    assert r["record_version"] == 2 and "trace" not in r
    arm = load_arm(old)
    again = gate.rescored(arm, GOLDEN)  # rescored from the saved answer, no call
    assert again.records[("synth-001", 0)]["score"] == r["score"]
    assert gate.cost(arm, {"gpt-4.1-mini": (0.40, 1.60)}) == pytest.approx(
        (r["input_tokens"] * 0.40 + r["output_tokens"] * 1.60) / 1e6
    )


def test_the_gate_prices_a_traced_record_by_its_steps(tmp_path):
    out = tmp_path / "runs.jsonl"
    record_run(program(tmp_path, {"synth-001": [{"answer": answer()}]}), out)
    arm = load_arm(out)
    assert gate.cost(arm, PRICES) == pytest.approx((230 * 1 + 15 * 2) / 1e6)
    assert gate.cost(arm, {"other": (1, 1)}) is None


def test_the_runner_cli_reads_a_price_table(tmp_path, capsys, monkeypatch):
    good, bad = tmp_path / "prices.yaml", tmp_path / "bad.yaml"
    good.write_text("fake-model: [1, 2]\n")
    bad.write_text("fake-model: 1\n")
    monkeypatch.chdir(
        FIXTURES
    )  # the config's command is relative to where the gate runs
    out = tmp_path / "o.jsonl"
    args = ["--config", "config.yaml", "--golden", str(GOLDEN), "--out", str(out)]
    with pytest.raises(SystemExit, match="USD per 1M tokens"):
        runner.main([*args, "--prices", str(bad)])
    runner.main([*args, "--prices", str(good)])
    assert "1 records written" in capsys.readouterr().out


def test_the_gate_prices_with_its_own_table_and_falls_back_to_answer_tokens(tmp_path):
    out = tmp_path / "runs.jsonl"
    record_run(
        program(tmp_path, {"synth-001": [{"answer": answer()}]}),
        out,
        prices={"fake-model": (100.0, 100.0)},
    )
    arm = load_arm(out)
    assert gate.cost(arm, PRICES) == pytest.approx(
        (230 * 1 + 15 * 2) / 1e6
    )  # the gate's table wins
    no_steps = tmp_path / "bare.jsonl"
    r = {
        **read_records(out)[0],
        "trace": {"v": 1, "steps": [], "stop": "done"},
        "input_tokens": 1000,
        "output_tokens": 0,
        "model": "fake-model-1",
    }
    no_steps.write_text(json.dumps(r) + "\n")
    assert gate.cost(load_arm(no_steps), PRICES) == pytest.approx(1000 / 1e6)


def test_the_runner_prices_the_usage_and_keeps_the_requested_model(tmp_path):
    from scripted import config

    prices = tmp_path / "prices.yaml"
    prices.write_text("fake-model: [1, 2]\n")
    path = config(tmp_path, {"synth-001": [{"answer": answer()}]})
    out = tmp_path / "o.jsonl"
    runner.main(
        [
            "--config",
            str(path),
            "--golden",
            str(GOLDEN),
            "--out",
            str(out),
            "--prices",
            str(prices),
        ]
    )
    [r] = read_records(out)
    assert r["requested_model"] == "fake-model-2026-01-01"  # next to the reported one
    assert [s["cost_usd"] for s in r["trace"]["steps"] if s["kind"] == "llm"] == [
        None,
        None,
    ]
    assert r["usage"]["agent"]["cost_usd"] == pytest.approx((230 * 1 + 15 * 2) / 1e6)


# cached input


def test_cached_input_costs_its_own_price(tmp_path):
    from llm_release_gate.prices import load_prices, usd

    table = tmp_path / "p.yaml"
    table.write_text("gpt-5.4-mini: [0.75, 4.50, 0.075]\ngpt-4.1-mini: [0.40, 1.60]\n")
    prices = load_prices(table)
    # 10 000 tokens in, 9 000 of them cached, 100 out
    assert usd("gpt-5.4-mini-2026-03-17", 10_000, 100, prices, 9_000) == pytest.approx(
        (1_000 * 0.75 + 9_000 * 0.075 + 100 * 4.50) / 1e6
    )
    # without a cached price, cached tokens cost the full input price, as before
    assert usd("gpt-4.1-mini-2025-04-14", 10_000, 100, prices, 9_000) == pytest.approx(
        (10_000 * 0.40 + 100 * 1.60) / 1e6
    )
    table.write_text("gpt-5.4-mini: [0.75, 4.50, 0.075, 1]\n")
    with pytest.raises(ValueError, match="cached input"):
        load_prices(table)


# review round 1 (25.10.)


@pytest.mark.parametrize("day", ["2026-10-06", "2026-10-12"])
def test_records_from_before_the_runner_still_read_score_and_cost(day):
    [r] = read_records(Path(__file__).parent / "fixtures" / "records" / f"{day}.jsonl")
    [case] = load_cases(GOLDEN)
    assert "trace" not in r and "config_hash" not in r
    assert metrics.score(case.expected, r["output"], case.scoring)["score"] == 1.0
    assert usd(
        r["model"],
        r["input_tokens"],
        r["output_tokens"],
        {"gpt-4.1-mini": (0.40, 1.60)},
    ) == pytest.approx((336 * 0.40 + 83 * 1.60) / 1e6)


def test_a_step_cannot_break_types_or_its_number():
    t = trace.Trace()
    with pytest.raises(ValueError, match="tokens_in"):
        t.step(
            "llm",
            "agent",
            status="ok",
            model="m",
            tokens_in=None,
            tokens_out=1,
            cost_usd=None,
        )
    with pytest.raises(ValueError, match="attempt"):
        t.step("llm", "agent", status="error", error="x", attempt=0)
    s = t.step("message", "agent", text="hi", seq=99, run_attempt=7)
    assert s["seq"] == 0 and s["run_attempt"] == 0


def test_a_result_json_cannot_hold_is_kept_as_its_repr():
    t = trace.Trace()
    t.step("tool", "agent", name="now", args={}, status="ok", result={"when": object()})
    assert t.steps[0]["result"]["when"].startswith("<object object")
    json.dumps(t.to_dict())


def test_the_last_attempt_may_have_no_steps_yet():
    t = trace.Trace()
    t.step("llm", "agent", status="error", error="x", attempt=1)
    t.run_attempt = 1
    assert trace.last_attempt(t.to_dict()) == []
    assert trace.Trace().empty() and not t.empty()


def test_values_json_cannot_hold_never_break_the_record(tmp_path):
    from datetime import date

    t = trace.Trace()
    t.final_state = {"when": date(2026, 11, 2)}
    t.step("message", "agent", text="hi", extra={"at": date(2026, 11, 2)})
    json.dumps(t.to_dict())
    assert t.to_dict()["final_state"] == {"when": "datetime.date(2026, 11, 2)"}
