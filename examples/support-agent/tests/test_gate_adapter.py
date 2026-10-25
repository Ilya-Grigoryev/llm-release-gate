import filecmp
from dataclasses import replace
from pathlib import Path

import openai
import pytest
from support_agent import gate_adapter, golden
from test_agent import FakeClient, call

from llm_release_gate import runner
from llm_release_gate.golden import load_cases, validate
from llm_release_gate.metrics import hits
from llm_release_gate.pipeline import Fatal, Retryable, config_hash, load_config
from llm_release_gate.runner import read_records

EXAMPLE = Path(__file__).parent.parent
CONFIG = EXAMPLE / "configs" / "support.yaml"


def gate_run(mode, client, case_id, out):
    """One golden case through the gate's runner, as `llm_release_gate.runner` would run it."""
    directory = EXAMPLE / "golden" / mode
    set_hash, errors = validate(directory)
    assert not errors
    cases = [c for c in load_cases(directory) if c.id == case_id]
    pipeline = gate_adapter.build(load_config(CONFIG), client=client)
    runner.run(
        pipeline,
        cases,
        1,
        out,
        config_hash="c" * 64,
        set_hash=set_hash,
        score=hits,
        workers=1,
    )
    [record] = read_records(out)
    return record


@pytest.mark.parametrize("mode", ["solo", "chat"])
def test_the_committed_golden_sets_match_the_cases(tmp_path, mode):
    golden.build(EXAMPLE / "cases", tmp_path / mode, mode)
    diff = filecmp.dircmp(EXAMPLE / "golden" / mode, tmp_path / mode)
    assert not diff.diff_files and not diff.left_only and not diff.right_only
    assert not filecmp.dircmp(
        EXAMPLE / "golden" / mode / "inputs", tmp_path / mode / "inputs"
    ).diff_files


def test_the_simulator_is_in_the_chat_set_hash_only():
    solo = load_cases(EXAMPLE / "golden" / "solo")
    chat = load_cases(EXAMPLE / "golden" / "chat")
    assert all("simulator" not in c.inputs for c in solo)
    assert all("simulator" in c.inputs for c in chat)
    assert (
        validate(EXAMPLE / "golden" / "solo")[0]
        != validate(EXAMPLE / "golden" / "chat")[0]
    )


def test_the_policy_and_the_tools_are_the_version(tmp_path):
    config = load_config(CONFIG)
    policy = tmp_path / "policy.md"
    policy.write_text((EXAMPLE / "policy.md").read_text().replace("€30", "€50"))
    edited = replace(config, prompt={**config.prompt, "policy": policy})
    assert config_hash(edited) != config_hash(config)


def test_a_good_run_passes_every_check_with_a_trace(tmp_path):
    client = FakeClient(
        [call("find_member", {"email": "jonas.weber@example.com"})],
        [call("cancel_booking", {"booking_id": "B-202"}, id="c2")],
        "Cancelled B-202. It starts in less than 24 hours, so there is no credit.",
    )
    r = gate_run("solo", client, "cancel-late", tmp_path / "runs.jsonl")
    assert r["error"] is None and r["score"] == 1.0
    assert r["hits"] == {
        "state": True,
        "acted": True,
        "verified": True,
        "credit-limit": True,
        "steps": True,
    }
    t = r["trace"]
    assert [(s["kind"], s["actor"]) for s in t["steps"]] == [
        ("llm", "agent"),
        ("tool", "agent"),
        ("llm", "agent"),
        ("tool", "agent"),
        ("llm", "agent"),
    ]
    assert [s.get("call_id") for s in t["steps"] if s["kind"] == "tool"] == ["c1", "c2"]
    assert t["state_change"] == {"cancelled": ["B-202"]} and t["stop"] == "done"
    assert any(
        b["id"] == "B-202" and b["status"] == "cancelled"
        for b in t["final_state"]["bookings"]
    )
    assert r["output"]["reply"].startswith("Cancelled B-202")
    assert r["usage"]["agent"]["llm_calls"] == 3


def test_a_policy_breach_fails_the_case(tmp_path):
    # the smoke run of 25.10.: a late cancellation credited anyway
    client = FakeClient(
        [call("find_member", {"email": "jonas.weber@example.com"})],
        [call("cancel_booking", {"booking_id": "B-202"}, id="c2")],
        [
            call(
                "issue_credit",
                {"member_id": "M-102", "amount_eur": 30, "reason": "refund"},
                id="c3",
            )
        ],
        "Cancelled and credited €30.",
    )
    r = gate_run("solo", client, "cancel-late", tmp_path / "runs.jsonl")
    assert r["score"] == 0.0
    assert (
        r["hits"]["state"] is False and r["hits"]["credit-limit"] is True
    )  # €30 is within the limit


def test_a_chat_records_the_member_apart(tmp_path):
    client = FakeClient(
        "Cancel my room today, please. jonas.weber@example.com",  # the member (simulator)
        [call("find_member", {"email": "jonas.weber@example.com"})],  # the agent
        [call("cancel_booking", {"booking_id": "B-202"}, id="c2")],
        "Done, no credit: it starts in less than 24 hours.",
        "Thanks! ###STOP###",  # the member
    )
    r = gate_run("chat", client, "cancel-late", tmp_path / "runs.jsonl")
    assert r["score"] == 1.0 and r["trace"]["stop"] == "user_stop"
    assert (
        r["usage"]["user"]["llm_calls"] == 2 and r["usage"]["agent"]["llm_calls"] == 3
    )
    actors = [s["actor"] for s in r["trace"]["steps"] if s["kind"] == "llm"]
    assert actors == ["user", "agent", "agent", "agent", "user"]


@pytest.mark.parametrize(
    "error, expected",
    [
        (
            lambda r: openai.RateLimitError(
                "slow", response=r(429), body={"code": "insufficient_quota"}
            ),
            Fatal,
        ),
        (
            lambda r: openai.AuthenticationError("bad key", response=r(401), body=None),
            Fatal,
        ),
        (lambda r: openai.APIConnectionError(request=None), Retryable),
    ],
)
def test_provider_errors_map_to_retry_or_stop(error, expected):
    def response(code):
        return type("R", (), {"status_code": code, "headers": {}, "request": None})()

    class Failing:
        def __init__(self):
            self.chat = type("C", (), {"completions": self})()

        def create(self, **request):
            e = error(response)
            if isinstance(e, openai.RateLimitError):
                e.code = "insufficient_quota"
            raise e

    pipeline = gate_adapter.build(load_config(CONFIG), client=Failing())
    with pytest.raises(expected):
        pipeline.run(load_cases(EXAMPLE / "golden" / "solo")[0])


def test_rate_limits_become_retries():
    class Limited:
        def __init__(self):
            self.chat = type("C", (), {"completions": self})()

        def create(self, **request):
            response = type(
                "R", (), {"status_code": 429, "headers": {}, "request": None}
            )()
            raise openai.RateLimitError("slow down", response=response, body=None)

    pipeline = gate_adapter.build(load_config(CONFIG), client=Limited())
    case = load_cases(EXAMPLE / "golden" / "solo")[0]
    with pytest.raises(Retryable):
        pipeline.run(case)


def test_the_prompt_must_name_policy_and_tools(tmp_path):
    config = replace(load_config(CONFIG), prompt=EXAMPLE / "policy.md")
    with pytest.raises(ValueError, match="policy and tools"):
        gate_adapter.build(config, client=FakeClient())
