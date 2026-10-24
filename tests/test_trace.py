from pathlib import Path

import pytest
from agent_pipeline import Adapter, ScriptedModel, World, agent, completion

from llm_release_gate import gate, runner, trace
from llm_release_gate.compare import load_arm
from llm_release_gate.golden import load_cases, validate
from llm_release_gate.metrics import hits
from llm_release_gate.runner import read_records

GOLDEN = Path(__file__).parent / "fixtures" / "golden"
PRICES = {"fake-model": (1.0, 2.0)}


def script():
    return ScriptedModel(
        [
            completion(calls=[("c1", "add", {"amount": 5})]),
            completion("Added 5.", tokens=(130, 5)),
        ]
    )


def record_run(adapter, out, **kw):
    set_hash, _ = validate(GOLDEN)
    return runner.run(
        adapter,
        load_cases(GOLDEN),
        1,
        out,
        config_hash="c" * 64,
        set_hash=set_hash,
        score=hits,
        workers=1,
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


# path 1 and path 2


def test_the_wrapped_client_records_each_call_and_rebuilds_tool_steps():
    t = trace.Trace(PRICES)
    with trace.active(t):
        reply = agent(trace.openai_client(script()), World(), "add 5")
    assert reply == "Added 5."
    llm, tool, llm2 = t.steps
    assert llm["kind"] == "llm" and llm["actor"] == "agent" and llm["status"] == "ok"
    assert (
        llm["model"] == "fake-model-2026-01-01" and llm["finish_reason"] == "tool_calls"
    )
    assert llm["tool_calls"] == [{"id": "c1", "name": "add", "args": {"amount": 5}}]
    assert llm["cost_usd"] == pytest.approx((100 * 1 + 10 * 2) / 1e6)
    assert llm["request_id"] == "req-1" and llm["fingerprint"] == "fp_1"
    assert tool == {
        **tool,
        "kind": "tool",
        "call_id": "c1",
        "name": "add",
        "args": {"amount": 5},
        "status": "unknown",
        "result": {"balance": 5},
    }
    assert llm2["text"] == "Added 5." and llm2["finish_reason"] == "stop"


def test_own_tool_steps_get_the_call_id_instead_of_a_copy():
    t = trace.Trace()
    world = World()
    world.call = trace.wrap_tool(world.call)
    with trace.active(t):
        agent(trace.openai_client(script()), world, "add 5")
    tools = [s for s in t.steps if s["kind"] == "tool"]
    assert len(tools) == 1
    assert tools[0]["status"] == "ok" and tools[0]["call_id"] == "c1"
    assert "latency_ms" in tools[0]


def test_a_tool_error_is_recorded_and_raised():
    t = trace.Trace()
    call = trace.wrap_tool(World().call)
    with trace.active(t), pytest.raises(ValueError):
        call("refund", {})
    assert t.steps[0]["status"] == "error" and "unknown tool" in t.steps[0]["error"]


def test_a_failed_model_call_is_a_step_and_counts_its_attempts():
    t = trace.Trace()
    client = trace.openai_client(
        ScriptedModel([TimeoutError("slow"), TimeoutError("slow")])
    )
    with trace.active(t):
        for _ in range(2):
            with pytest.raises(TimeoutError):
                client.chat.completions.create(model="fake", messages=[])
    assert [(s["status"], s["attempt"]) for s in t.steps] == [
        ("error", 1),
        ("error", 2),
    ]


def test_outside_the_runner_the_wrappers_pass_calls_through():
    assert trace.current() is None
    reply = agent(trace.openai_client(script()), World(), "add 5")
    assert reply == "Added 5."


def test_the_wrapped_client_keeps_the_rest_of_the_client():
    model = script()
    model.models = "the models API"
    assert trace.openai_client(model).models == "the models API"


# through the runner


def test_a_record_holds_the_trace_its_usage_and_the_raw_responses(tmp_path):
    out = tmp_path / "runs.jsonl"
    model = script()
    model_dump = {"id": "req-1"}
    for reply in model.script:
        reply.model_dump = lambda mode, d=model_dump: d
    record_run(Adapter({"synth-001": lambda: model}), out, prices=PRICES)
    [r] = read_records(out)
    assert r["record_version"] == 3 and r["error"] is None and r["wall_s"] >= 0
    t = r["trace"]
    assert t["v"] == 1 and t["stop"] == "done" and t["final_state"] == {"balance": 5}
    assert [s["kind"] for s in t["steps"]] == ["llm", "tool", "llm"]
    assert (
        r["usage"]["agent"]["llm_calls"] == 2
        and r["usage"]["agent"]["tokens_in"] == 230
    )
    assert t["native"] == "runs.native.jsonl"
    [raw] = read_records(tmp_path / "runs.native.jsonl")
    assert raw["case"] == "synth-001" and raw["native"] == [model_dump, model_dump]


def test_a_failed_run_keeps_the_steps_it_paid_for(tmp_path):
    out = tmp_path / "runs.jsonl"
    broken = lambda: ScriptedModel(
        [completion(calls=[("c1", "add", {"amount": 5})]), KeyError("boom")]
    )
    record_run(Adapter({"synth-001": broken}), out)
    [r] = read_records(out)
    assert r["error"].startswith("KeyError") and r["output"] is None
    assert [(s["kind"], s["status"]) for s in r["trace"]["steps"]] == [
        ("llm", "ok"),
        ("tool", "ok"),  # the adapter wraps its tools, so the step is its own
        ("llm", "error"),
    ]
    assert r["usage"]["agent"]["llm_calls"] == 1


def test_a_retried_run_keeps_both_attempts_and_checks_see_the_last(tmp_path):
    out = tmp_path / "runs.jsonl"
    scripts = iter(
        [
            ScriptedModel(
                [completion(calls=[("c1", "add", {"amount": 5})]), TimeoutError("slow")]
            ),
            script(),
        ]
    )
    record_run(Adapter({"synth-001": lambda: next(scripts)}), out, wait=lambda s: False)
    [r] = read_records(out)
    assert r["error"] is None and r["retries"] == 1
    attempts = [s["run_attempt"] for s in r["trace"]["steps"]]
    assert attempts == [0, 0, 0, 1, 1, 1]  # llm, tool, failed llm; llm, tool, llm
    assert r["usage"]["agent"]["llm_calls"] == 3  # all paid
    assert len(trace.last_attempt(r["trace"])) == 3


def test_a_pipeline_without_a_trace_writes_the_record_as_before(tmp_path):
    out = tmp_path / "runs.jsonl"
    from replay_pipeline import Replay

    record_run(Replay(), out)
    [r] = read_records(out)
    assert r["trace"] is None and r["usage"] is None and r["score"] is not None
    assert not (tmp_path / "runs.native.jsonl").exists()


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
    record_run(Adapter({"synth-001": script}), out)  # no prices at run time
    arm = load_arm(out)
    assert gate.cost(arm, PRICES) == pytest.approx((230 * 1 + 15 * 2) / 1e6)
    assert gate.cost(arm, {"other": (1, 1)}) is None


def test_the_runner_cli_reads_a_price_table(tmp_path, capsys):
    good, bad = tmp_path / "prices.yaml", tmp_path / "bad.yaml"
    good.write_text("fake-model: [1, 2]\n")
    bad.write_text("fake-model: 1\n")
    config = Path(__file__).parent / "fixtures" / "config.yaml"
    out = tmp_path / "o.jsonl"
    args = ["--config", str(config), "--golden", str(GOLDEN), "--out", str(out)]
    with pytest.raises(SystemExit, match="USD per 1M tokens"):
        runner.main([*args, "--prices", str(bad)])
    runner.main([*args, "--prices", str(good)])
    assert "1 records written" in capsys.readouterr().out
