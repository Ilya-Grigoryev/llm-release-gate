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
        ({"checks": [{"kind": "active"}]}, "text id"),
        (
            {"checks": [{"id": "a", "kind": "active"}, {"id": "a", "kind": "active"}]},
            "clashes",
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
            "checks": [
                {
                    "id": "f",
                    "kind": "field_match",
                    **{k: v for k, v in golden["scoring"].items() if k != "method"},
                }
            ],
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


# review round 1 (25.10.)


@pytest.mark.parametrize(
    "spec, error",
    [
        ({"kind": "regex", "pattern": "("}, "bad pattern"),
        ({"kind": "json_schema", "schema": {"type": 5}}, "bad schema"),
        ({"kind": "actions", "actions": [{"args": {}}]}, "list of {tool, args}"),
        ({"kind": "max_steps", "max": "15"}, "whole number"),
        (
            {"kind": "order", "first": "a", "then": "cancel_booking"},
            "list of tool names",
        ),
        (
            {
                "kind": "not_called",
                "tool": "issue_credit",
                "args": {"amount_eur": {"ge": 30}},
            },
            "operators",
        ),
        ({"kind": "active", "actor": "agnet"}, "actor"),
        ({"kind": "called", "tool": "x", "args": ["amount"]}, "args must be a mapping"),
        ({"kind": "number", "field": "total", "value": 1, "tol": "abc"}, "tol"),
        ({"kind": "exact", "field": "reply", "expected": "rply"}, "no 'rply'"),
        ({"kind": "state", "key": "final_state"}, "no 'final_state'"),
        ({"kind": "doc_found", "ids": "d1"}, "list of document ids"),
        ({"kind": "function", "function": "math:pi"}, "not callable"),
    ],
)
def test_validation_catches_a_bad_config_without_running_it(spec, error):
    found = checks.validate(EXPECTED, {"checks": [{"id": "c", **spec}]})
    assert any(error in f for f in found), found


def test_validation_does_not_call_a_team_function(tmp_path, monkeypatch):
    (tmp_path / "picky.py").write_text(
        "def reply(expected, output, trace, spec):\n    return output['reply']\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    assert (
        checks.validate(
            EXPECTED,
            {"checks": [{"id": "c", "kind": "function", "function": "picky:reply"}]},
        )
        == []
    )


def test_id_clashes_are_found_in_any_order():
    for ids in (["a", "a.x"], ["a.x", "a"]):
        found = checks.validate(
            EXPECTED, {"checks": [{"id": i, "kind": "active"} for i in ids]}
        )
        assert any("clashes" in f for f in found)


def test_a_refused_forbidden_call_still_counts_as_tried():
    tried = {
        **TRACE,
        "steps": [
            step(
                0,
                "tool",
                name="issue_credit",
                args={"amount_eur": "60"},
                status="error",
            )
        ],
    }
    assert check(
        "not_called", trace=tried, tool="issue_credit", args={"amount_eur": {"gt": 30}}
    ) == {"c": False}
    assert check("called", trace=tried, tool="issue_credit") == {
        "c": False
    }  # it did not go through


def test_no_answer_is_not_a_refusal():
    assert check("refusal", None, expected="refuse") == {"c": False}
    assert check("refusal", {}, expected="refuse") == {"c": False}


def test_plain_numbers_compare_by_value():
    assert check("number", {"total": "1e-07"}, field="total", value=0.0000001) == {
        "c": True
    }
    assert check("number", {"total": 45}, field="total", value="45.00") == {"c": True}


def test_the_runner_and_the_gate_give_the_same_verdicts_on_a_trace(tmp_path):
    from scripted import answer, program

    from llm_release_gate import gate, runner
    from llm_release_gate.compare import load_arm
    from llm_release_gate.golden import load_cases

    golden = tmp_path / "golden"
    (golden / "inputs").mkdir(parents=True)
    for name in ("synth-001.txt", "synth-001.jpg"):
        (golden / "inputs" / name).write_bytes(b"x")
    case = yaml.safe_load(
        (Path(__file__).parent / "fixtures" / "golden" / "synth-001.yaml").read_text()
    )
    case["expected"] = {"state_change": {"balance": 5}}
    case["scoring"] = {
        "method": "checks",
        "aggregate": "all",
        "checks": [
            {"id": "state", "kind": "state", "key": "state_change"},
            {"id": "acted", "kind": "active"},
            {
                "id": "added",
                "kind": "called",
                "tool": "add",
                "args": {"amount": {"gte": 5}},
            },
        ],
    }
    (golden / "synth-001.yaml").write_text(yaml.safe_dump(case))
    set_hash, errors = validate(golden)
    assert not errors
    out = tmp_path / "runs.jsonl"
    runner.run(
        program(tmp_path, {"synth-001": [{"answer": answer()}]}),
        load_cases(golden),
        1,
        out,
        config_hash="c" * 64,
        set_hash=set_hash,
        score=metrics.hits,
        workers=1,
    )
    arm = load_arm(out)
    [record] = arm.records.values()
    assert (
        record["hits"] == {"state": True, "acted": True, "added": True}
        and record["score"] == 1.0
    )
    [again] = gate.rescored(arm, golden).records.values()
    assert again["hits"] == record["hits"] and again["score"] == record["score"]


# review round 2 (25.10.)


def test_a_broken_team_module_is_a_validation_error(tmp_path, monkeypatch):
    (tmp_path / "broken_checks.py").write_text("def polite(:\n")
    (tmp_path / "loud_checks.py").write_text("raise RuntimeError('boom')\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    for module in ("broken_checks", "loud_checks"):
        found = checks.validate(
            EXPECTED,
            {
                "checks": [
                    {"id": "c", "kind": "function", "function": f"{module}:polite"}
                ]
            },
        )
        assert found and "cannot load" in found[0]


@pytest.mark.parametrize(
    "spec, error",
    [
        (
            {
                "kind": "not_called",
                "tool": "issue_credit",
                "args": {"amount_eur": {"gt": "30"}},
            },
            "gt needs a number",
        ),
        ({"kind": "called", "tool": "x", "args": {"n": {"in": 5}}}, "in needs a list"),
        (
            {
                "kind": "called",
                "tool": "issue_credit",
                "arg": {"amount_eur": {"gt": 100}},
            },
            "unknown keys ['arg']",
        ),
        (
            {"kind": "regex", "feild": "reply", "pattern": "B-1"},
            "unknown keys ['feild']",
        ),
        ({"kind": "refusal", "value": "false"}, "true or false"),
        ({"kind": "contains", "field": "reply", "value": ""}, "empty value"),
    ],
)
def test_round_two_configs_are_refused(spec, error):
    found = checks.validate(EXPECTED, {"checks": [{"id": "c", **spec}]})
    assert any(error in f for f in found), found


def test_a_function_check_may_carry_its_own_keys(tmp_path, monkeypatch):
    (tmp_path / "keyed.py").write_text(
        "def at_least(expected, output, trace, spec):\n    return output['n'] >= spec['min']\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    assert check("function", {"n": 3}, function="keyed:at_least", min=2) == {"c": True}


def test_odd_answers_and_results_do_not_crash():
    assert check("number", {"total": "NaN"}, field="total", value=1) == {"c": False}
    schema = {"$ref": "https://example.invalid/schema.json"}
    assert check("json_schema", {"a": 1}, schema=schema) == {"c": False}


def test_a_team_function_must_return_a_result(tmp_path, monkeypatch):
    (tmp_path / "wrong.py").write_text(
        "def score(expected, output, trace, spec):\n    return 'yes'\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    with pytest.raises(ValueError, match="returned 'yes'"):
        check("function", {}, function="wrong:score")
