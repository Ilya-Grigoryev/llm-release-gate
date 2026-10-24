from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from llm_release_gate import checks, metrics
from llm_release_gate.golden import validate


def step(seq, kind, actor="agent", attempt=0, **fields):
    return {"seq": seq, "kind": kind, "actor": actor, "run_attempt": attempt, **fields}


TRACE = {
    "v": 1,
    "steps": [
        step(
            0, "llm", status="ok", model="m", tokens_in=1, tokens_out=1, cost_usd=None
        ),
        step(1, "tool", name="find_member", args={"email": "a@x.org"}, status="ok"),
        step(2, "tool", name="cancel_booking", args={"booking_id": "B-1"}, status="ok"),
        step(3, "tool", name="issue_credit", args={"amount_eur": 45.0}, status="ok"),
        step(4, "tool", name="escalate_to_human", args={}, status="error"),
        step(
            5, "llm", status="ok", model="m", tokens_in=1, tokens_out=1, cost_usd=None
        ),
        step(
            6,
            "llm",
            status="ok",
            purpose="compaction",
            model="m",
            tokens_in=1,
            tokens_out=1,
            cost_usd=None,
        ),
        step(7, "tool", "user", name="toggle_roaming", args={}, status="ok"),
        step(8, "retrieval", docs=[{"id": "d1"}, {"id": "d2"}]),
    ],
    "final_state": {"balance": 5},
    "state_change": {"cancelled": ["B-1"]},
    "stop": "done",
}
EXPECTED = {
    "reply": "B-1",
    "total": "12.50",
    "fields": {"company": "TEST MART", "total": "12.50"},
    "actions": [
        {"tool": "find_member"},
        {"tool": "cancel_booking", "args": {"booking_id": "B-1"}},
        {"tool": "create_booking"},
    ],
    "state_change": {"cancelled": ["B-1"]},
    "docs": ["d1", "d3"],
    "refuse": True,
}


def check(kind, output=None, trace=TRACE, **spec):
    return checks.run(
        EXPECTED, output, {"checks": [{"id": "c", "kind": kind, **spec}]}, trace
    )


# answer checks


def test_field_match_inside_checks_keeps_the_field_rules():
    got = check(
        "field_match",
        {"company": " test mart ", "total": "RM 12.5"},
        normalise=["whitespace", "casefold"],
        fields={"total": {"type": "number"}},
    )
    assert got == {"c.company": True, "c.total": True}


@pytest.mark.parametrize(
    "kind, spec, output, want",
    [
        ("exact", {"field": "reply", "value": "Done"}, {"reply": " Done "}, True),
        ("exact", {"field": "reply", "expected": "reply"}, {"reply": "B-2"}, False),
        (
            "contains",
            {"field": "reply", "value": "b-1"},
            {"reply": "Booking B-1 is off"},
            True,
        ),
        (
            "regex",
            {"field": "reply", "pattern": r"B-\d+"},
            {"reply": "no number"},
            False,
        ),
        ("regex", {"field": "reply", "pattern": r"B-\d+"}, None, False),
        (
            "number",
            {"field": "total", "expected": "total", "tol": 0.01},
            {"total": "12.505"},
            True,
        ),
        ("number", {"field": "total", "expected": "total"}, {"total": "12.6"}, False),
        (
            "json_schema",
            {"schema": {"type": "object", "required": ["reply"]}},
            {"reply": 1},
            True,
        ),
        (
            "json_schema",
            {"schema": {"type": "object", "required": ["reply"]}},
            {},
            False,
        ),
        ("refusal", {"expected": "refuse"}, {"answer": None}, True),
        ("refusal", {"expected": "refuse"}, {"answer": "Paris"}, False),
        ("refusal", {"value": False}, {"answer": "Paris"}, True),
    ],
)
def test_answer_checks(kind, spec, output, want):
    assert check(kind, output, **spec) == {"c": want}


# trace checks


@pytest.mark.parametrize(
    "kind, spec, want",
    [
        ("called", {"tool": "cancel_booking", "args": {"booking_id": "B-1"}}, True),
        ("called", {"tool": "cancel_booking", "args": {"booking_id": "B-2"}}, False),
        ("called", {"tool": "escalate_to_human"}, False),  # it failed
        ("called", {"tool": "toggle_roaming"}, False),  # the user did it
        ("called", {"tool": "toggle_roaming", "actor": "user"}, True),
        (
            "not_called",
            {"tool": "issue_credit", "args": {"amount_eur": {"gt": 30}}},
            False,
        ),
        (
            "not_called",
            {"tool": "issue_credit", "args": {"amount_eur": {"gt": 50}}},
            True,
        ),
        ("not_called", {"tool": "create_booking"}, True),
        (
            "order",
            {"first": "find_member", "then": ["cancel_booking", "issue_credit"]},
            True,
        ),
        ("order", {"first": "issue_credit", "then": ["cancel_booking"]}, False),
        (
            "order",
            {"first": "find_member", "then": ["create_booking"]},
            True,
        ),  # nothing to order
        ("max_steps", {"max": 2}, True),  # housekeeping is not a step
        ("max_steps", {"max": 1}, False),
        ("active", {}, True),
        ("state", {"key": "state_change"}, True),
        ("state", {"key": "final_state", "expected": "state_change"}, False),
        ("doc_found", {"expected": "docs"}, 0.5),
    ],
)
def test_trace_checks(kind, spec, want):
    assert check(kind, **spec) == {"c": want}


def test_expected_actions_give_one_result_each():
    assert check("actions", expected="actions") == {
        "c.0:find_member": True,
        "c.1:cancel_booking": True,
        "c.2:create_booking": False,
    }


def test_trace_checks_fail_without_a_trace_and_see_only_the_last_attempt():
    assert check("active", trace=None) == {"c": False}
    assert check("state", trace=None, key="state_change") == {"c": False}
    retried = {
        **TRACE,
        "steps": [
            step(0, "tool", name="find_member", args={}, status="ok"),
            step(
                1,
                "llm",
                attempt=1,
                status="ok",
                model="m",
                tokens_in=1,
                tokens_out=1,
                cost_usd=None,
            ),
        ],
    }
    assert check("active", trace=retried) == {
        "c": False
    }  # the tool call was in the abandoned attempt


def test_a_simulator_that_did_the_work_fails_activity():
    # smoke 24.10. (R-011): state reached, the agent never called a tool
    lazy = {
        **TRACE,
        "steps": [step(0, "tool", "user", name="toggle_roaming", args={}, status="ok")],
    }
    assert check("active", trace=lazy) == {"c": False}
    assert check("state", trace=lazy, key="state_change") == {"c": True}


def test_own_function(tmp_path, monkeypatch):
    (tmp_path / "team_checks.py").write_text(
        "def polite(expected, output, trace, spec):\n    return 'please' in output['reply']\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    assert check(
        "function", {"reply": "please wait"}, function="team_checks:polite"
    ) == {"c": True}
    with pytest.raises(ValueError, match="cannot load"):
        check("function", function="team_checks:missing")


# aggregation and configuration


def test_aggregate_mean_or_all():
    results = {"a": True, "b": False, "c": None, "d": 0.5}
    assert metrics.aggregate(results, "mean") == pytest.approx(0.5)
    assert metrics.aggregate(results, "all") == 0.0
    assert metrics.aggregate({"a": True, "b": 1.0, "c": None}, "all") == 1.0
    assert metrics.aggregate({"a": None}, "all") is None


def test_score_aggregates_checks_as_the_case_says():
    config = {
        "method": "checks",
        "aggregate": "all",
        "checks": [
            {"id": "s", "kind": "state", "key": "state_change"},
            {"id": "x", "kind": "not_called", "tool": "issue_credit"},
        ],
    }
    result = metrics.score(EXPECTED, None, config, TRACE)
    assert result == {"score": 0.0, "per_field": {"s": True, "x": False}}
    assert (
        metrics.score(EXPECTED, None, {**config, "aggregate": "mean"}, TRACE)["score"]
        == 0.5
    )


@pytest.mark.parametrize(
    "config, error",
    [
        ({"checks": []}, "non-empty"),
        ({"checks": [{"id": "a", "kind": "telepathy"}]}, "unknown kind"),
        ({"checks": [{"kind": "active"}]}, "id and a kind"),
        (
            {"checks": [{"id": "a", "kind": "active"}, {"id": "a", "kind": "active"}]},
            "twice",
        ),
        ({"checks": [{"id": "a", "kind": "called"}]}, "missing tool"),
        ({"checks": [{"id": "a", "kind": "regex"}]}, "missing pattern"),
        ({"checks": [{"id": "a", "kind": "exact", "field": "reply"}]}, "give `value`"),
        (
            {"checks": [{"id": "a", "kind": "state", "key": "mood"}]},
            "final_state or state_change",
        ),
        ({"checks": [{"id": "a", "kind": "active"}], "aggregate": "most"}, "aggregate"),
    ],
)
def test_bad_check_configs_are_refused(config, error):
    with pytest.raises((ValueError, TypeError), match=error):
        metrics.score(EXPECTED, None, {"method": "checks", **config}, TRACE)


def test_golden_validate_reports_a_bad_check(tmp_path):
    case = yaml.safe_load(
        (Path(__file__).parent / "fixtures" / "golden" / "synth-001.yaml").read_text()
    )
    (tmp_path / "inputs").mkdir()
    for name in ("synth-001.txt", "synth-001.jpg"):
        (tmp_path / "inputs" / name).write_bytes(b"x")
    case["scoring"] = {"method": "checks", "checks": [{"id": "a", "kind": "telepathy"}]}
    (tmp_path / "synth-001.yaml").write_text(yaml.safe_dump(case))
    _, errors = validate(tmp_path)
    assert errors and "unknown kind" in errors[0]


def test_field_match_cases_score_as_before():
    golden = yaml.safe_load(
        (Path(__file__).parent / "fixtures" / "golden" / "synth-001.yaml").read_text()
    )
    answer = {
        "company": "TEST MART SDN BHD",
        "date": "1/1/2026",
        "address": "wrong",
        "total": "12.5",
    }
    old = metrics.score(golden["expected"], answer, golden["scoring"])
    via_checks = metrics.score(
        {"fields": golden["expected"]},
        answer,
        {
            "method": "checks",
            "checks": [{"id": "f", "kind": "field_match", **golden["scoring"]}],
        },
    )
    assert old["score"] == via_checks["score"] == 0.75
    assert {f"f.{k}": v for k, v in old["per_field"].items()} == via_checks["per_field"]


def test_the_runner_scores_a_case_as_its_aggregate_says(tmp_path):
    from replay_pipeline import Replay

    from llm_release_gate import runner
    from llm_release_gate.golden import load_cases
    from llm_release_gate.runner import read_records

    golden = Path(__file__).parent / "fixtures" / "golden"
    [case] = load_cases(golden)
    strict = replace(case, scoring={**case.scoring, "aggregate": "all"})
    out = tmp_path / "runs.jsonl"
    wrong_date = Replay().answers[0]
    wrong_date = replace(wrong_date, output={**wrong_date.output, "date": "02/02/2020"})
    runner.run(
        Replay(answers=[wrong_date]),
        [strict],
        1,
        out,
        config_hash="c" * 64,
        set_hash="s" * 64,
        score=metrics.hits,
        workers=1,
    )
    [r] = read_records(out)
    assert (
        r["hits"]["date"] is False and r["score"] == 0.0
    )  # 3 of 4 fields right, but `all`
