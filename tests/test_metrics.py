import copy
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from llm_release_gate.golden import load_cases
from llm_release_gate.metrics import hits, mean, parse_date, parse_number, score
from llm_release_gate.pipeline import Answer

FIXTURES = Path(__file__).parent / "fixtures"
SPACE_CASE = {"method": "field_match", "normalise": ["whitespace", "casefold"]}
EXACT = {"method": "field_match"}
TYPED = {
    **SPACE_CASE,
    "fields": {"date": {"type": "date"}, "total": {"type": "number"}},
}

# Expected values, answer, scoring config -> per-field verdicts and score, counted by hand.
HAND_COUNTED = [
    pytest.param(
        {"company": "KEDAI UJI .K SDN BHD", "date": "01/02/2026", "total": "9.00"},
        {"company": "kedai uji .k  sdn bhd", "date": "01/02/2026", "address": "X"},
        SPACE_CASE,
        {"company": True, "date": True, "total": False},
        2 / 3,
        id="case-and-spacing-ignored-missing-field-wrong-extra-field-ignored",
    ),
    pytest.param(
        {"company": "KEDAI UJI", "date": "01/02/2026"},
        {"company": "kedai uji", "date": " 01/02/2026"},
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
    pytest.param(
        {"company": "Kedai Uji", "date": "25/12/2018", "total": "9.00"},
        {"company": "KEDAI UJI", "date": "25/12/2018 8:13:39 PM", "total": "RM 9.0"},
        TYPED,
        {"company": True, "date": True, "total": True},
        1.0,
        id="date-and-total-by-value",
    ),
    pytest.param(
        {"date": "25/12/2018", "total": "9.00"},
        {"date": "26/12/2018", "total": "9.01"},
        TYPED,
        {"date": False, "total": False},
        0.0,
        id="a-different-date-or-amount-is-wrong",
    ),
    pytest.param(
        {"date": "25/12/2018", "total": "9.00"},
        {"date": "Christmas", "total": "nine"},
        TYPED,
        {"date": False, "total": False},
        0.0,
        id="an-answer-that-does-not-parse-is-wrong",
    ),
    pytest.param(
        {"date": "sometime", "total": "N/A"},
        {"date": " SOMETIME", "total": "n/a"},
        TYPED,
        {"date": True, "total": True},
        1.0,
        id="a-label-that-does-not-parse-falls-back-to-text",
    ),
    pytest.param(
        {"company": "Kedai Uji"},
        {"company": "KEDAI  UJI"},
        {**SPACE_CASE, "fields": {"company": {"normalise": []}}},
        {"company": False},
        0.0,
        id="field-normalisers-override-the-default",
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
        ({"method": "field_match", "normalise": "casefold"}, "must be a list"),
        (None, "scoring must be a mapping"),
        (
            {"method": "field_match", "fields": {"total": {"type": "money"}}},
            "unknown type",
        ),
        ({"method": "field_match", "fields": ["total"]}, "fields must be a mapping"),
    ],
)
def test_unknown_scoring_is_an_error(config, message):
    with pytest.raises((ValueError, TypeError), match=message):
        score({"company": "A"}, {"company": "A"}, config)


@pytest.mark.parametrize(
    "text, day",
    [
        ("25/01/2018", date(2018, 1, 25)),
        ("10-01-16", date(2016, 1, 10)),
        ("21 JUN 2018", date(2018, 6, 21)),
        ("20/JAN/2017", date(2017, 1, 20)),
        ("29 JUN 18", date(2018, 6, 29)),
        ("2018-05-01", date(2018, 5, 1)),
        ("20180428", date(2018, 4, 28)),
        ("25032018", date(2018, 3, 25)),
        ("4/22/2018", date(2018, 4, 22)),  # month first when day first is impossible
        ("23.03.18", date(2018, 3, 23)),
        ("OCT 3, 2016", date(2016, 10, 3)),
        ("DATE: 03/10/2018 10:42:15", date(2018, 10, 3)),
        ("12:30:45", None),
        ("", None),
        ("MAR 2018", None),  # no day: the year must not lend one
        ("Dec 2018", None),
        ("25th December 2018", date(2018, 12, 25)),
        ("05 02 18", date(2018, 2, 5)),
        ("05 02-18", date(2018, 2, 5)),
        ("25/12/201", None),
        (
            "31/02/2018 25/12/2018",
            date(2018, 12, 25),
        ),  # an impossible date does not end the search
        ("25/12/2018 ref 2018-01-02", date(2018, 12, 25)),  # the first one
    ],
)
def test_parse_date(text, day):
    assert parse_date(text) == day


@pytest.mark.parametrize(
    "text, amount",
    [
        ("190.80", Decimal("190.8")),
        ("RM7.70", Decimal("7.7")),
        ("RM 59.20", Decimal("59.2")),
        ("$7.80", Decimal("7.8")),
        ("-6.42", Decimal("-6.42")),
        ("1,007.50", Decimal("1007.5")),
        ("12,50", None),
        ("abc", None),
    ],
)
def test_parse_number(text, amount):
    assert parse_number(text) == amount


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


def test_a_month_without_a_day_does_not_match_a_full_date():
    assert score({"date": "20/03/2018"}, {"date": "MAR 2018"}, TYPED)["per_field"] == {
        "date": False
    }
