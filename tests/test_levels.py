import pytest

from llm_release_gate.levels import Levels, case_score

RULES = Levels.parse(
    {
        "critical": ["state", "credit-*"],
        "minor": ["steps", "state"],
        "cases": {"probe-*": "minor", "vip-*": "critical"},
    }
)


@pytest.mark.parametrize(
    "case, check, level",
    [
        ("probe-1", "state", "minor"),  # a minor case makes every check minor
        ("book-1", "state", "critical"),  # critical wins over minor for the same check
        ("book-1", "credit-limit", "critical"),
        ("book-1", "steps", "minor"),
        ("vip-1", "reply", "critical"),  # the case's level for a check without its own
        ("vip-1", "steps", "minor"),  # the check's own level first
        ("book-1", "reply", "normal"),
    ],
)
def test_the_first_matching_rule_sets_the_level(case, check, level):
    assert RULES.of(case, check) == level


def test_without_rules_everything_is_normal():
    assert not Levels.parse(None) and Levels().of("a", "b") == "normal"


def test_unknown_case_level_is_refused():
    with pytest.raises(ValueError, match="unknown level 'low'"):
        Levels.parse({"cases": {"a": "low"}})


def test_patterns_that_match_nothing_are_named():
    keys = [("book-1", "state"), ("book-1", "steps")]
    assert RULES.unmatched(keys) == [
        "critical: credit-*",
        "cases: probe-*",
        "cases: vip-*",
    ]


def test_positional_ids_match_by_pattern():
    # telecom's assertion checks are numbered: assert-0 is the first assertion of each task, not one meaning
    rules = Levels.parse({"critical": ["assert-0"], "minor": ["action-*"]})
    assert [rules.of(t, c) for t, c in [("t1", "assert-0"), ("t1", "assert-1"), ("t2", "assert-0"), ("t1", "action-3")]] == [
        "critical", "normal", "critical", "minor"]  # fmt: skip


@pytest.mark.parametrize(
    "hits, how, score",
    [
        ({"state": True, "steps": False}, "all", 1.0),  # the minor miss does not count
        ({"state": False, "steps": True}, "all", 0.0),
        ({"company": 1.0, "steps": 0.0, "total": 0.5}, "mean", 0.75),
        ({"steps": False}, "all", None),  # only minor checks: no score
        (None, "all", None),
    ],
)
def test_the_case_score_leaves_out_minor_checks(hits, how, score):
    assert case_score("book-1", hits, how, RULES) == score


@pytest.mark.parametrize(
    "raw, message",
    [
        ({"critical": "total"}, "levels.critical must be a list"),
        ({"critcal": ["x"]}, "levels take critical, minor"),
        ({"cases": ["x"]}, "levels.cases must map"),
        (["x"], "levels take critical, minor"),
    ],
)
def test_malformed_levels_are_refused(raw, message):
    with pytest.raises(ValueError, match=message):
        Levels.parse(raw)
