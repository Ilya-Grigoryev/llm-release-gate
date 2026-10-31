import random
from fractions import Fraction

import pytest

from llm_release_gate.criterion import can_block, fisher, per_check, runs_to_block


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


def test_tarone_with_two_noisy_checks_can_turn_a_block_into_a_pass():
    base, cand = (
        {("a", "x"): runs(5, 5)},
        {("a", "x"): runs(1, 5)},
    )  # p = 1/42, blocks alone
    assert per_check(base, cand).outcome == "block"
    for case in ("b", "c"):
        base[case, "x"], cand[case, "x"] = runs(5, 10), runs(5, 10)
    v = per_check(base, cand)
    assert (v.m, v.outcome) == (
        2,
        "pass",
    )  # 1/42 > 0.025 / 2: the noisy checks raised the correction


def test_checks_scored_in_one_version_only_are_named():
    v = per_check(
        {("a", "x"): [True], ("b", "x"): [True]},
        {("a", "x"): [True], ("b", "x"): [None]},
    )
    assert v.one_sided == [("b", "x")]


def test_alpha_may_be_any_number():
    v = per_check(
        {("c", "x"): runs(3, 3)}, {("c", "x"): runs(0, 3)}, alpha=Fraction(1, 20)
    )
    assert v.outcome == "block"


def test_false_blocks_stay_under_alpha_when_nothing_changed():
    """A smoke test near the boundary (true rate ~1 %); the full null tests are T-25's."""
    rng, blocks, sims = random.Random(0), 0, 2000
    for _ in range(sims):
        base = {
            (f"c{i}", "x"): [rng.random() < 0.5 for _ in range(5)] for i in range(10)
        }
        cand = {
            (f"c{i}", "x"): [rng.random() < 0.5 for _ in range(5)] for i in range(10)
        }
        blocks += per_check(base, cand).outcome == "block"
    assert blocks / sims <= 0.025


@pytest.mark.parametrize(
    "alpha, sides, k",
    [(0.025, 1, 4), (0.05, 1, 3), (0.05, 2, 4), (0.001, 1, 7)],
)
def test_runs_to_block_is_the_fewest_runs_a_full_break_needs(alpha, sides, k):
    assert runs_to_block(alpha, sides) == k
    full = per_check(
        {("c", "x"): runs(k, k)}, {("c", "x"): runs(0, k)}, alpha=alpha, sides=sides
    )
    fewer = per_check(
        {("c", "x"): runs(k - 1, k - 1)},
        {("c", "x"): runs(0, k - 1)},
        alpha=alpha,
        sides=sides,
    )
    assert (full.outcome, fewer.outcome, fewer.testable) == ("block", "pass", 0)


@pytest.mark.parametrize("alpha, sides", [(0, 1), (1, 1), (0.05, 3)])
def test_runs_to_block_refuses_bad_arguments(alpha, sides):
    with pytest.raises(ValueError):
        runs_to_block(alpha, sides)


@pytest.mark.parametrize(
    "kb, kc, alpha, sides, possible",
    [(3, 3, 0.025, 1, False), (4, 4, 0.025, 1, True), (10, 1, 0.025, 1, False), (10, 2, 0.025, 1, True),
     (3, 3, 0.05, 1, True), (3, 3, 0.05, 2, False)],
)  # fmt: skip
def test_can_block_depends_only_on_the_run_counts(kb, kc, alpha, sides, possible):
    assert can_block(kb, kc, alpha, sides) is possible
