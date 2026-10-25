"""tau2's real orchestrator, environment and evaluator on a real telecom task, with the model scripted: no network.

Needs tau2's data (`sh fetch_data.sh`); without it the tests are skipped.
"""

import json
from pathlib import Path

import litellm
import pytest
import tau2_example
import yaml

from llm_release_gate import runner, trace
from llm_release_gate.golden import load_cases, validate
from llm_release_gate.metrics import hits
from llm_release_gate.pipeline import Fatal, Retryable, load_config, load_pipeline
from llm_release_gate.runner import read_records

if not (tau2_example.DATA / "tau2" / "domains" / "telecom").is_dir():
    pytest.skip("no tau2 data: run sh fetch_data.sh", allow_module_level=True)

from tau2.runner import load_task_splits, load_tasks
from tau2_example import golden

TASK = "[mobile_data_issue]user_abroad_roaming_enabled_off[PERSONA:None]"  # small; the user only toggles roaming
POLICY = tau2_example.DATA / "tau2" / "domains" / "telecom"
MODEL = "fake-model-2026-01-01"


def response(content=None, calls=(), model=MODEL, tokens=(100, 10)):
    message = {"role": "assistant", "content": content}
    if calls:
        message["tool_calls"] = [
            {
                "id": cid,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            }
            for cid, name, args in calls
        ]
    return litellm.ModelResponse(
        id="req-1",
        model=model,
        system_fingerprint="fp_1",
        choices=[
            {
                "index": 0,
                "message": message,
                "finish_reason": "tool_calls" if calls else "stop",
            }
        ],
        usage={"prompt_tokens": tokens[0], "completion_tokens": tokens[1]},
    )


class Script:
    """Stands in for litellm.completion: answers each call from a list; an exception in the list is raised."""

    def __init__(self, replies):
        self.replies, self.requests = list(replies), []

    def __call__(self, **request):
        self.requests.append(request)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


@pytest.fixture
def script(monkeypatch):
    def install(replies):
        s = Script(replies)
        monkeypatch.setattr("tau2.utils.llm_utils.completion", s)
        return s

    return install


def config(tmp_path, main_solo=POLICY / "main_policy_solo.md"):
    path = tmp_path / "telecom.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "pipeline": "tau2_example.gate_adapter",
                "model": MODEL,
                "prompt": {
                    "main": str(POLICY / "main_policy.md"),
                    "main_solo": str(main_solo),
                    "tech_support": str(POLICY / "tech_support_manual.md"),
                },
                "input": "task",
                "params": {"temperature": 0},
            }
        )
    )
    return load_config(path)


def golden_set(tmp_path, mode, ids=(TASK,)):
    out = tmp_path / f"golden-{mode}"
    golden.build(list(ids), load_task_splits("telecom"), out, mode, golden.USER)
    return out


def reference_calls():
    """The task's expected actions as one scripted tool call each, then `done`."""
    [task] = [t for t in load_tasks("telecom") if t.id == TASK]
    calls = [
        response(calls=[(f"c{i}", a.name, a.arguments)])
        for i, a in enumerate(task.evaluation_criteria.actions)
    ]
    return calls + [response(calls=[("stop", "done", {})])]


def run_case(tmp_path, mode="solo", cfg=None):
    [case] = load_cases(golden_set(tmp_path, mode))
    t = trace.Trace()
    with trace.active(t):
        answer = load_pipeline(cfg or config(tmp_path)).run(case)
    return answer, t


def test_the_reference_actions_solve_the_task_through_the_runner(tmp_path, script):
    script(reference_calls())
    out_dir = golden_set(tmp_path, "solo")
    set_hash, _ = validate(out_dir)
    out = tmp_path / "runs.jsonl"
    runner.run(load_pipeline(config(tmp_path)), load_cases(out_dir), 1, out, config_hash="c" * 64,
               set_hash=set_hash, score=hits, workers=1)  # fmt: skip
    [r] = read_records(out)
    assert r["error"] is None and r["score"] == 1.0, r["hits"]
    assert r["output"]["reward"] == 1.0 and r["output"]["termination"] == "agent_stop"
    assert set(r["hits"]) == {
        "reward",
        "assert-0",
        "assert-1",
        "action-0-toggle_roaming",
        "agent-acted",
    }
    tools = [s for s in r["trace"]["steps"] if s["kind"] == "tool"]
    assert [(s["actor"], s["name"]) for s in tools] == [
        ("agent", "toggle_roaming")
    ]  # `done` stops, it runs nothing
    assert r["trace"]["stop"] == "done" and r["model"] == MODEL
    assert r["usage"]["agent"] == {
        "llm_calls": 2,
        "tokens_in": 200,
        "tokens_out": 20,
        "cost_usd": None,
    }


def test_an_agent_that_only_stops_fails_reward_and_conduct(tmp_path, script):
    script([response(calls=[("stop", "done", {})])])
    answer, t = run_case(tmp_path)
    assert answer.output["reward"] == 0.0 and set(
        answer.output["assertions"].values()
    ) == {0}
    assert [s["kind"] for s in t.steps] == ["llm"] and t.stop == "done"


def test_the_policy_comes_from_the_config(tmp_path, script):
    edited = tmp_path / "main_policy_solo.md"
    edited.write_text(
        (POLICY / "main_policy_solo.md").read_text() + "\nMARKER-FROM-THE-PR\n"
    )
    s = script([response(calls=[("stop", "done", {})])])
    run_case(tmp_path, cfg=config(tmp_path, main_solo=edited))
    system = s.requests[0]["messages"][0]
    assert system["role"] == "system" and "MARKER-FROM-THE-PR" in system["content"]
    assert s.requests[0]["num_retries"] == 0  # the runner retries, not litellm


def test_a_chat_records_the_simulated_user_as_its_own_actor(tmp_path, script):
    s = script([response("###STOP###", model="sim-model-2026-01-01", tokens=(50, 5))])
    answer, t = run_case(tmp_path, "chat")
    assert (
        answer.output["termination"] == "user_stop" and answer.output["reward"] == 0.0
    )
    assert [(x["kind"], x["actor"]) for x in t.steps] == [
        ("message", "agent"),
        ("llm", "user"),
    ]
    assert (
        t.steps[1]["model"] == "sim-model-2026-01-01" and answer.model is None
    )  # the agent made no model call
    assert s.requests[0]["model"] == golden.USER["model"] and t.stop == "user_stop"


def test_a_rate_limit_retries_and_keeps_the_paid_steps(tmp_path, script):
    limited = litellm.RateLimitError("slow down", llm_provider="openai", model=MODEL)
    script([response(calls=[("c0", "toggle_roaming", {})]), limited])
    [case] = load_cases(golden_set(tmp_path, "solo"))
    t = trace.Trace()
    with trace.active(t), pytest.raises(Retryable):
        load_pipeline(config(tmp_path)).run(case)
    assert [(s["kind"], s.get("name")) for s in t.steps] == [
        ("llm", None),
        ("tool", "toggle_roaming"),
    ]


def test_no_quota_stops_the_run(tmp_path, script):
    script(
        [
            litellm.RateLimitError(
                "insufficient_quota: check your plan",
                llm_provider="openai",
                model=MODEL,
            )
        ]
    )
    with pytest.raises(Fatal, match="insufficient_quota"):
        run_case(tmp_path)


def test_a_simulator_that_differs_from_the_golden_set_stops_the_run(tmp_path, script):
    out_dir = golden_set(tmp_path, "chat")
    run_yaml = out_dir / "inputs" / "run.yaml"
    run = yaml.safe_load(run_yaml.read_text())
    run["user"]["guidelines_sha256"] = "0" * 64
    run_yaml.write_text(yaml.safe_dump(run))
    [case] = load_cases(out_dir)
    with pytest.raises(Fatal, match="differs from the simulator"):
        load_pipeline(config(tmp_path)).run(case)


def test_the_simulator_is_part_of_the_set_hash(tmp_path):
    solo, chat = (
        validate(golden_set(tmp_path, "solo"))[0],
        validate(golden_set(tmp_path, "chat"))[0],
    )
    other = tmp_path / "other"
    golden.build(
        [TASK],
        load_task_splits("telecom"),
        other,
        "chat",
        {**golden.USER, "model": "gpt-6-luna"},
    )
    assert len({solo, chat, validate(other)[0]}) == 3


def test_chat_checks_only_the_agents_own_actions():
    [task] = [
        t for t in load_tasks("telecom") if t.id == TASK
    ]  # its one expected action is the user's
    assert [c["id"] for c in golden.checks(task, solo=True)] == [
        "reward", "assert-0", "assert-1", "action-0-toggle_roaming", "agent-acted"]  # fmt: skip
    assert [c["id"] for c in golden.checks(task, solo=False)] == [
        "reward",
        "assert-0",
        "assert-1",
        "agent-acted",
    ]


def test_the_manifests_name_tasks_tau2_has():
    ids = {t.id for t in load_tasks("telecom")}
    for mode in ("solo", "chat"):
        manifest = yaml.safe_load(
            (Path(__file__).parents[1] / "golden" / f"telecom-{mode}.yaml").read_text()
        )
        assert set(manifest["tasks"]) <= ids and len(manifest["tasks"]) == 30
        assert manifest["ids"] == sorted(golden.case_id(t) for t in manifest["tasks"])
