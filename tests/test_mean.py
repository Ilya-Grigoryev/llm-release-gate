import math
import random

import pytest

from llm_release_gate import mean

METHODS = [
    {"unit": "case", "bet": "betting", "c": 0.5},
    {"unit": "case", "bet": "betting", "c": 0.75},
    {"unit": "case", "bet": "bernstein", "c": 0.75},
    {"unit": "run", "bet": "betting", "c": 0.75},
]


def arms(
    n: int, k: int, base: float = 1.0, candidate: float = 1.0
) -> tuple[dict, dict]:
    return {f"c{i:03}": [base] * k for i in range(n)}, {
        f"c{i:03}": [candidate] * k for i in range(n)
    }


@pytest.mark.parametrize(
    "n, delta, method, runs",
    [
        (
            53,
            0.05,
            METHODS[1],
            2,
        ),  # ln 40 / ln(1 + c delta / (1 - delta)) = 96 case runs
        (53, 0.05, METHODS[0], 3),  # 143
        (30, 0.05, METHODS[1], 4),
        (10, 0.05, METHODS[1], 10),
        (53, 0.05, METHODS[2], 4),  # Bernstein: ln 40 / (c delta / 2) = 197
        (1, 0.05, METHODS[3], 96),  # one bet per run
    ],
)
def test_silence_passes_at_the_predicted_run(n, delta, method, runs):
    assert mean.runs_for_pass(n, delta, 0.025, **method) == runs
    b, c = arms(n, runs)
    v = mean.decide(b, c, delta, **method)
    assert (v.outcome, v.decided_at, v.runs_for_pass) == ("pass", runs, runs)
    assert v.lower > -delta and v.upper > 0
    if runs > 2:
        b, c = arms(n, runs - 1)
        assert mean.decide(b, c, delta, **method).outcome == "inconclusive"


def test_never_before_min_runs():
    b, c = arms(100, 1)
    v = mean.decide(b, c, 0.05, c=0.75)
    assert (v.outcome, v.runs, v.runs_for_pass) == ("inconclusive", 1, 2)
    assert mean.runs_for_pass(1, 0.02, 0.025, unit="run", c=0.5, cap=50) is None


@pytest.mark.parametrize("method", METHODS)
def test_a_broken_candidate_blocks(method):
    b, c = arms(30, 6, base=1.0, candidate=0.0)
    v = mean.decide(b, c, 0.05, **method)
    assert v.diff == -1.0
    if method["unit"] == "run":  # six bets cannot reach 1 / alpha
        assert v.outcome == "inconclusive"
    else:
        assert (v.outcome, v.decided_at) == ("block", 2) and v.upper < -0.05


def test_bounds_contain_the_observed_difference():
    rng = random.Random(1)
    b = {f"c{i}": [float(rng.random() < 0.8) for _ in range(5)] for i in range(40)}
    c = {k: [float(rng.random() < 0.7) for _ in range(5)] for k in b}
    for method in METHODS:
        v = mean.decide(b, c, 0.05, **method)
        assert -1 <= v.lower <= v.diff <= v.upper <= 1


def test_pass_shown_worse_warns():
    b, c = arms(400, 4)
    c = {
        k: [0.0] + runs[1:] if i < 8 else runs for i, (k, runs) in enumerate(c.items())
    }  # 8 of 1600 case runs lost
    v = mean.decide(b, c, 0.05, c=0.75)
    assert v.outcome == "pass" and v.upper < 0 and v.worse


def test_pairs_runs_by_number_and_drops_the_extra():
    b = {"a": [1.0, 1.0, 0.0], "b": [1.0, 1.0]}
    c = {"a": [1.0, 0.0, 1.0, 1.0], "b": [0.5, 1.0, 1.0]}
    assert mean.observations(b, c) == [[0.5, 0.25], [0.0, 0.5]]


@pytest.mark.parametrize(
    "b, c",
    [
        ({}, {}),
        ({"a": [1.0]}, {"b": [1.0]}),
        ({"a": []}, {"a": [1.0]}),
        ({"a": [1.2]}, {"a": [1.0]}),
        ({"a": [True]}, {"a": [1.0]}),
    ],
)
def test_rejects_bad_input(b, c):
    with pytest.raises(ValueError):
        mean.decide(b, c, 0.05)


def test_rejects_bad_parameters():
    b, c = arms(3, 2)
    for kw in ({"unit": "x"}, {"bet": "x"}, {"c": 1.0}):
        with pytest.raises(ValueError):
            mean.decide(b, c, 0.05, **kw)
    for delta in (0, 1):
        with pytest.raises(ValueError):
            mean.decide(b, c, delta)


@pytest.mark.parametrize("method", METHODS[:3])
def test_worst_case_regression_rarely_passes(method):
    """D-026's worst case at the boundary: the base always right, the candidate wrong in each case run with chance
    delta. Over every look up to 12 runs the rule may pass at most alpha of the time (here: 0 of 400 is expected)."""
    rng, n, k, delta = random.Random(7), 10, 12, 0.05
    passed = 0
    for _ in range(400):
        ys = [[float(rng.random() >= delta) / 2 for _ in range(n)] for _ in range(k)]
        steps = mean.capitals(ys, (1 - delta) / 2, 0.025, **method)
        passed += mean.first(steps, 0.025)[0] == "pass"
    assert passed <= 400 * 0.025 + 3 * math.sqrt(400 * 0.025 * 0.975)


def test_the_verdict_counts_differing_runs_and_reports_an_interval_over_cases():
    b = {"a": [1.0, 1.0], "b": [1.0, 1.0], "c": [0.0, 1.0]}
    c = {"a": [1.0, 0.0], "b": [1.0, 1.0], "c": [1.0, 1.0]}
    v = mean.decide(b, c, 0.05)
    assert v.nonzero == 2 and v.diff == 0.0
    half = 1.959964 * 0.5 / math.sqrt(3)  # per case: -0.5, 0, +0.5
    assert v.similar_cases == pytest.approx((-half, half))


def test_the_bounds_are_those_of_the_look_that_decided():
    # two clean runs pass 100 cases; later runs lose 15 % but cannot undo the pass, and the bounds must not contradict it
    b = {f"c{i:03}": [1.0] * 6 for i in range(100)}
    c = {
        k: [1.0, 1.0] + [0.0 if (i + r) % 7 == 0 else 1.0 for r in range(4)]
        for i, k in enumerate(b)
    }
    v = mean.decide(b, c, 0.05)
    assert (v.outcome, v.decided_at) == ("pass", 2)
    assert v.lower > -0.05 and not v.worse
    assert v.diff < -0.05  # over all six runs
