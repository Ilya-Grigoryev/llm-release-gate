import random
from fractions import Fraction

import pytest

from llm_release_gate.criterion import fisher, per_check


def runs(k, n):
    return [True] * k + [False] * (n - k)


def same(units, n=5):
    """Checks that always pass in both versions: they cannot reach significance, so Tarone leaves them out."""
    return {(f"case-{i}", "state"): runs(n, n) for i in range(units)}


@pytest.mark.parametrize(
    "x, kb, y, kc, sides, p",
    [
        (5, 5, 0, 5, 1, Fraction(1, 252)),
        (3, 3, 0, 3, 1, Fraction(1, 20)),
        (
            10,
            10,
            0,
            2,
            1,
            Fraction(1, 66),
        ),  # a base with more runs, as from a cache (D-011)
        (5, 5, 0, 5, 2, Fraction(1, 126)),
        (2, 5, 2, 5, 1, Fraction(31, 42)),
    ],
)
def test_fisher_gives_the_exact_p(x, kb, y, kc, sides, p):
    assert fisher(x, kb, y, kc, sides)[0] == p


def test_one_broken_check_blocks_among_many_that_cannot_change():
    base, cand = same(200), same(200)
    base["case-0", "refusal"], cand["case-0", "refusal"] = runs(5, 5), runs(0, 5)
    v = per_check(base, cand)
    assert v.outcome == "block" and v.m == 1 and v.testable == 1
    assert [(u.case, u.check, u.base, u.candidate) for u in v.broken] == [
        ("case-0", "refusal", (5, 5), (0, 5))
    ]


def test_a_p_of_exactly_alpha_blocks_and_three_runs_cannot_reach_the_default():
    base, cand = {("c", "x"): runs(3, 3)}, {("c", "x"): runs(0, 3)}
    assert per_check(base, cand).outcome == "pass"  # 1/20 > 0.025
    assert per_check(base, cand, alpha=0.05).outcome == "block"  # 1/20 <= 0.05, exactly


def test_a_cached_base_with_more_runs_lets_two_candidate_runs_block():
    v = per_check({("c", "x"): runs(10, 10)}, {("c", "x"): runs(0, 2)})
    assert v.outcome == "block" and v.broken[0].p == pytest.approx(1 / 66)


def test_report_mode_lists_without_blocking():
    v = per_check({("c", "x"): runs(5, 5)}, {("c", "x"): runs(0, 5)}, mode="report")
    assert v.outcome == "report" and len(v.broken) == 1


def test_an_improvement_never_blocks_even_two_sided():
    v = per_check(
        {("c", "x"): runs(0, 5)}, {("c", "x"): runs(5, 5)}, sides=2, alpha=0.05
    )
    assert v.outcome == "pass" and v.units[0].p < 0.05


def test_unscored_runs_are_left_out_and_shares_pass_at_the_threshold():
    base = {("c", "doc"): [1.0, 1.0, 1.0, 1.0, 1.0, None]}
    cand = {("c", "doc"): [0.5, 0.5, 0.5, 0.5, 0.5, None]}
    assert per_check(base, cand).broken[0].candidate == (0, 5)
    assert per_check(base, cand, threshold=0.5).outcome == "pass"


def test_bad_inputs_are_refused():
    with pytest.raises(ValueError):
        per_check({("c", "x"): [True]}, {("d", "x"): [True]})
    with pytest.raises(ValueError):
        per_check({("c", "x"): [True]}, {("c", "x"): [True]}, alpha=0)
    with pytest.raises(ValueError):
        per_check({("c", "x"): [True]}, {("c", "x"): [True]}, mode="warn")


def test_noisy_checks_raise_the_correction():
    rng = random.Random(1)
    base = {(f"c{i}", "x"): [rng.random() < 0.5 for _ in range(10)] for i in range(40)}
    cand = {(f"c{i}", "x"): [rng.random() < 0.5 for _ in range(10)] for i in range(40)}
    v = per_check(base, cand)
    assert v.m > 1 and v.testable <= v.m


def test_false_blocks_stay_under_alpha_when_nothing_changed():
    rng, blocks, sims = random.Random(0), 0, 400
    probs = (
        [1.0] * 12 + [0.0] * 9 + [rng.uniform(0.2, 0.8) for _ in range(9)]
    )  # 30 checks, as in the D-015 model
    for _ in range(sims):
        base = {
            (f"c{i}", "x"): [rng.random() < p for _ in range(5)]
            for i, p in enumerate(probs)
        }
        cand = {
            (f"c{i}", "x"): [rng.random() < p for _ in range(5)]
            for i, p in enumerate(probs)
        }
        blocks += per_check(base, cand).outcome == "block"
    assert (
        blocks / sims <= 0.025 + 0.02
    )  # Bonferroni over Tarone's set controls the chance of any false block
