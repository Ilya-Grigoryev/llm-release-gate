import itertools
import math
import random
from fractions import Fraction

import pytest

from llm_release_gate import criterion
from llm_release_gate.criterion import (
    can_block,
    fisher,
    per_check,
    runs_to_block,
    weak,
    whole_runs,
)


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


# The gate's rule: the test over whole runs (D-030). Tarone's `per_check` above stays for the experiments.


def reference(base, candidate, alpha=Fraction(1, 40)):
    """Step-down minP over every split, slowly and in exact fractions: the named checks and their adjusted p."""
    kb, kc = (max(map(len, arm.values())) for arm in (base, candidate))
    rows = {
        k: base[k]
        + [None] * (kb - len(base[k]))
        + candidate[k]
        + [None] * (kc - len(candidate[k]))
        for k in base
    }
    live = [
        k
        for k in sorted(rows)
        if 0 < sum(v is True for v in rows[k]) < sum(v is not None for v in rows[k])
    ]

    def p(key, split):
        b = [v for i, v in enumerate(rows[key]) if i in split and v is not None]
        c = [v for i, v in enumerate(rows[key]) if i not in split and v is not None]
        return fisher(sum(b), len(b), sum(c), len(c), 1)[0]

    splits = [set(s) for s in itertools.combinations(range(kb + kc), kb)]
    real = {k: p(k, splits[0]) for k in live}
    order = sorted(live, key=lambda k: real[k])
    adj, top = {}, Fraction(0)
    for j, key in enumerate(order):
        hits = sum(min(p(k, s) for k in order[j:]) <= real[key] for s in splits)
        top = max(top, Fraction(hits, len(splits)))
        adj[key] = top

    def worse(key):
        b, c = (
            [v for v in rows[key][a:z] if v is not None]
            for a, z in ((0, kb), (kb, kb + kc))
        )
        return b and c and sum(c) * len(b) < sum(b) * len(c)

    return {k for k in live if adj[k] <= alpha and worse(k)}, adj


@pytest.mark.parametrize("kb, kc", [(4, 4), (5, 3), (2, 6), (3, 3), (5, 5)])
def test_whole_runs_names_what_a_slow_reference_names(kb, kc):
    rng = random.Random(kb * 10 + kc)
    for _ in range(15):
        base, cand = {}, {}
        for i in range(5):
            fail = rng.random() < 0.4  # the case's checks fail together in a bad run
            for check in ("x", "y"):
                b = [rng.random() < (0.3 if fail else 0.8) for _ in range(kb)]
                c = [
                    rng.random() < (0.1 if fail and check == "x" else 0.8)
                    for _ in range(kc)
                ]
                for arm in (b, c):
                    if (
                        rng.random() < 0.3
                    ):  # an unscored run, or a missing one at the end
                        arm[rng.randrange(len(arm))] = None
                    if rng.random() < 0.2:
                        arm.pop()
                base[f"c{i}", check], cand[f"c{i}", check] = b, c
        named, adj = reference(base, cand)
        v = whole_runs(base, cand)
        assert {(u.case, u.check) for u in v.broken} == named
        assert all(u.adjusted == float(adj.get((u.case, u.check), 1)) for u in v.units)
        assert v.splits == math.comb(kb + kc, kb) and v.runs == (kb, kc)


def full(k, n, cases=1, check="x"):
    return {(f"c{i}", check): runs(k, n) for i in range(cases)}


def test_any_number_of_checks_broken_in_every_run_blocks():
    """Tarone's rule blocks none of 7 or more at 5 + 5 runs (E-008); the test over whole runs blocks them all."""
    base, cand = full(5, 5, 30) | same(200), full(0, 5, 30) | same(200)
    v = whole_runs(base, cand)
    assert v.outcome == "block" and len(v.broken) == 30
    assert v.broken[0].adjusted == pytest.approx(1 / 252)
    assert per_check(base, cand).outcome == "pass"


def test_a_pull_request_like_workbench_6_blocks_on_its_ten_broken_checks():
    """Experiment E-008, workbench #6: two checks of five cases fail in every candidate run; other checks of the set
    pass in every run or vary a little. Tarone's rule passed it (m = 7); here all ten are named."""
    pattern = {  # (base, candidate) runs that vary, 1 = pass
        ("a", "state"): ("01100", "10111"),
        ("b", "honest"): ("11111", "11101"),
        ("c", "honest"): ("01111", "11111"),
        ("d", "honest"): ("11111", "01111"),
        ("e", "honest"): ("11111", "11101"),
        ("f", "honest"): ("11101", "11111"),
        ("g", "honest"): ("10111", "11111"),
        ("h", "honest"): ("11111", "11101"),
    }
    pattern |= {
        (f"broke-{i}", check): ("11111", "00000")
        for i in range(5)
        for check in ("state", "limit")
    }
    base, cand = same(306), same(306)
    for key, (b, c) in pattern.items():
        base[key], cand[key] = [x == "1" for x in b], [x == "1" for x in c]
    v = whole_runs(base, cand)
    assert v.outcome == "block" and {u.case for u in v.broken} == {
        f"broke-{i}" for i in range(5)
    }
    assert (
        len(v.broken) == 10
        and per_check(base, cand).m == 7
        and per_check(base, cand).outcome == "pass"
    )


def test_at_4_runs_a_break_blocks_alone_but_one_check_varying_in_another_pattern_stops_it():
    noisy = {
        ("v", "x"): [True, True, False, False]
    }  # with the break's 4 base runs: another split as bad
    noisy_c = {("v", "x"): [True, True, False, False]}
    assert whole_runs(full(4, 4), full(0, 4)).outcome == "block"
    assert whole_runs(full(4, 4) | noisy, full(0, 4) | noisy_c).outcome == "pass"
    assert weak(4, 4) and not weak(5, 5)
    five = {("v", "x"): [True, True, False, False, True]}
    assert (
        whole_runs(
            full(5, 5) | five,
            full(0, 5) | {("v", "x"): [False, True, True, False, False]},
        ).outcome
        == "block"
    )


@pytest.mark.parametrize(
    "alpha, most", [(0.005, 1), (0.0125, 3), (0.025, 6), (0.05, 12)]
)
def test_at_5_runs_a_break_blocks_while_few_other_checks_share_its_extremity(
    alpha, most
):
    """Checks with 5 passes in 10 runs, each in its own pattern, each make one more split as bad as the real one."""
    patterns = [s for s in itertools.combinations(range(10), 5) if s != (0, 1, 2, 3, 4)]

    def blocks(n):
        base, cand = full(5, 5), full(0, 5)
        for i, s in enumerate(patterns[: n - 1]):
            row = [j in s for j in range(10)]
            base["v", f"x{i}"], cand["v", f"x{i}"] = row[:5], row[5:]
        return whole_runs(base, cand, alpha=alpha).outcome == "block"

    assert blocks(most) and not blocks(most + 1)
    assert most == math.floor(alpha * 252)


@pytest.mark.parametrize(
    "alpha, k", [(0.025, 4), (0.0125, 5), (0.005, 5), (0.05, 3), (0.0005, 7)]
)
def test_runs_to_block_is_the_fewest_runs_a_full_break_needs(alpha, k):
    assert runs_to_block(alpha) == k
    assert whole_runs(full(k, k), full(0, k), alpha=alpha).outcome == "block"
    assert whole_runs(full(k - 1, k - 1), full(0, k - 1), alpha=alpha).outcome == "pass"


def test_below_one_random_split_in_2000_no_number_of_runs_can_block():
    assert runs_to_block(0.0004) is None and not can_block(10, 10, 0.0004)


@pytest.mark.parametrize(
    "kb, kc, alpha, possible",
    [(3, 3, 0.025, False), (4, 4, 0.025, True), (10, 1, 0.025, False), (10, 2, 0.025, True), (3, 3, 0.05, True)],
)  # fmt: skip
def test_can_block_depends_only_on_the_run_counts(kb, kc, alpha, possible):
    assert can_block(kb, kc, alpha) is possible
    assert (
        whole_runs(full(kb, kb), full(0, kc), alpha=alpha).outcome == "block"
    ) is possible


def test_from_7_runs_the_splits_are_random_and_the_seed_fixes_them():
    base, cand = (
        full(8, 8, 2) | {("v", "x"): runs(4, 8)},
        full(0, 8, 2) | {("v", "x"): runs(4, 8)},
    )
    v = whole_runs(base, cand, seed=7)
    assert (v.outcome, v.splits, v.seed) == ("block", criterion.SPLITS + 1, 7)
    assert v == whole_runs(base, cand, seed=7)
    assert criterion.splits(8, 8, 7) != criterion.splits(8, 8, 8)
    assert criterion.splits(8, 8, 7)[0] == 0b11111111  # the real split first
    assert v.broken[0].adjusted == pytest.approx(1 / 2000)


def test_a_cached_base_with_more_runs_lets_two_candidate_runs_block_the_test_too():
    v = whole_runs({("c", "x"): runs(10, 10)}, {("c", "x"): runs(0, 2)})
    assert (
        v.outcome == "block"
        and v.splits == 66
        and v.broken[0].adjusted == pytest.approx(1 / 66)
    )


def test_an_unscored_result_moves_with_its_run_and_a_one_sided_check_is_never_named():
    base = {
        ("c", "x"): [True] * 5,
        ("c", "y"): [True, None, True, True, True],
        ("d", "z"): [True] * 5,
    }
    cand = {("c", "x"): [False] * 5, ("c", "y"): [False] * 5, ("d", "z"): [None] * 5}
    v = whole_runs(base, cand)
    assert v.one_sided == [("d", "z")] and [
        u.candidate for u in v.units if u.check == "y"
    ] == [(0, 5)]
    assert {u.check for u in v.broken} == {"x", "y"}
    named, _ = reference(base, cand)
    assert named == {("c", "x"), ("c", "y")}


def test_the_test_reads_the_first_ten_runs_of_each_version():
    v = whole_runs(
        full(12, 12), full(2, 12)
    )  # the candidate's 2 passes are in its first runs
    assert (v.runs, v.cut, v.broken[0].candidate) == ((10, 10), True, (2, 10))
    assert not whole_runs(full(10, 10), full(0, 10)).cut


def test_report_mode_names_without_blocking_and_shares_pass_at_the_threshold():
    v = whole_runs({("c", "x"): [1.0] * 5}, {("c", "x"): [0.5] * 5}, mode="report")
    assert v.outcome == "report" and len(v.broken) == 1
    assert (
        whole_runs(
            {("c", "x"): [1.0] * 5}, {("c", "x"): [0.5] * 5}, threshold=0.5
        ).outcome
        == "pass"
    )


def test_an_improvement_is_never_named():
    assert whole_runs(full(0, 5), full(5, 5)).outcome == "pass"


def test_whole_runs_refuses_bad_inputs():
    for args, kw in [
        (({("c", "x"): [True]}, {("d", "x"): [True]}), {}),
        (({("c", "x"): [True]}, {("c", "x"): [True]}), {"alpha": 0}),
        (({("c", "x"): [True]}, {("c", "x"): [True]}), {"mode": "warn"}),
    ]:
        with pytest.raises(ValueError):
            whole_runs(*args, **kw)


def test_false_blocks_stay_under_alpha_with_unequal_runs_and_gaps():
    """A smoke test: checks of a case fail together, the base has more runs, some results are missing."""
    rng, blocks, sims = random.Random(3), 0, 400
    for _ in range(sims):
        base, cand = {}, {}
        for i in range(8):
            for arm, k in ((base, 6), (cand, 4)):
                bad = [rng.random() < 0.3 for _ in range(k)]
                for check in ("x", "y"):
                    arm[f"c{i}", check] = [
                        None if rng.random() < 0.1 else not (b and rng.random() < 0.8)
                        for b in bad
                    ]
        blocks += whole_runs(base, cand).outcome == "block"
    assert blocks / sims <= 0.025
