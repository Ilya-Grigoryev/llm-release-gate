import copy
import json
from pathlib import Path

import pytest

from llm_release_gate.golden import load_cases
from llm_release_gate.metrics import hits, mean, score
from llm_release_gate.pipeline import Answer

FIXTURES = Path(__file__).parent / "fixtures"
SPACE_CASE = {"method": "field_match", "normalise": ["whitespace", "casefold"]}
EXACT = {"method": "field_match"}

# Expected values, answer, scoring config -> per-field verdicts and score, counted by hand.
HAND_COUNTED = [
    pytest.param(
        {"company": "BOOK TA .K SDN BHD", "date": "25/12/2018", "total": "9.00"},
        {"company": "book ta .k  sdn bhd", "date": "25/12/2018", "address": "X"},
        SPACE_CASE,
        {"company": True, "date": True, "total": False},
        2 / 3,
        id="case-and-spacing-ignored-missing-field-wrong-extra-field-ignored",
    ),
    pytest.param(
        {"company": "BOOK TA", "date": "25/12/2018"},
        {"company": "book ta", "date": " 25/12/2018"},
        EXACT,
        {"company": False, "date": False},
        0.0,
        id="no-normalisation-means-exact",
    ),
    pytest.param(
        {"company": "A", "total": None},
        {"company": "a", "total": "1.00"},
        SPACE_CASE,
        {"company": True, "total": None},
        1.0,
        id="null-expected-is-unscored-not-wrong",
    ),
    pytest.param(
        {"company": None, "total": None},
        {"company": "a"},
        SPACE_CASE,
        {"company": None, "total": None},
        None,
        id="nothing-scored-no-score",
    ),
    pytest.param(
        {"company": "A", "total": "1.00"},
        None,
        SPACE_CASE,
        {"company": False, "total": False},
        0.0,
        id="unparsed-answer-is-wrong",
    ),
    pytest.param(
        {"company": "A", "total": "1.00"},
        ["A", "1.00"],
        SPACE_CASE,
        {"company": False, "total": False},
        0.0,
        id="answer-not-an-object-is-wrong",
    ),
    pytest.param(
        {"total": "12.50", "count": 3},
        {"total": 12.5, "count": "3"},
        SPACE_CASE,
        {"total": False, "count": True},
        0.5,
        id="values-compared-as-text",
    ),
]


@pytest.mark.parametrize("expected, actual, config, per_field, value", HAND_COUNTED)
def test_hand_counted(expected, actual, config, per_field, value):
    result = score(expected, actual, config)
    assert result["per_field"] == per_field
    if value is None:
        assert result["score"] is None
    else:
        assert result["score"] == pytest.approx(value)


def test_score_does_not_touch_its_inputs():
    expected, actual = {"company": " A "}, {"company": "a"}
    before = copy.deepcopy((expected, actual, SPACE_CASE))
    score(expected, actual, SPACE_CASE)
    assert (expected, actual, SPACE_CASE) == before


@pytest.mark.parametrize(
    "config, message",
    [
        ({"method": "llm_judge"}, "unknown scoring method 'llm_judge'"),
        ({}, "unknown scoring method None"),
        ({"method": "field_match", "normalise": ["punctuation"]}, "unknown normaliser"),
    ],
)
def test_unknown_scoring_is_an_error(config, message):
    with pytest.raises(ValueError, match=message):
        score({"company": "A"}, {"company": "A"}, config)


def test_mean_skips_unscored_fields():
    assert mean({"a": True, "b": False, "c": None}) == 0.5
    assert mean({"a": None}) is None and mean({}) is None


def test_golden_case_scored_by_its_own_config():
    [case] = load_cases(FIXTURES / "golden")
    lines = (FIXTURES / "replay" / "synth-001.jsonl").read_text().splitlines()
    answers = [Answer(**json.loads(line)) for line in lines]
    # the third recorded answer reads the total as 12.60 instead of 12.50
    assert [hits(case, a)["total"] for a in answers] == [True, True, False, True]
    assert [score(case.expected, a.output, case.scoring)["score"] for a in answers] == [
        1.0,
        1.0,
        0.75,
        1.0,
    ]
