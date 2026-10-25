import json
import random

import pytest
from test_gate import Fixed, runs

from llm_release_gate import budget, gate


def test_the_median_interval_uses_the_textbook_ranks():
    # n = 100, 95 %: the 40th and 61st order statistics
    assert budget.quantile_ci([float(x) for x in range(1, 101)], 0.5) == (
        50.0,
        40.0,
        61.0,
    )


def test_an_end_is_missing_when_there_are_too_few_runs():
    est, lo, hi = budget.quantile_ci([float(x) for x in range(1, 72)], 0.95)
    assert (est, hi) == (68.0, None) and lo is not None
    assert budget.quantile_ci([float(x) for x in range(1, 73)], 0.95)[2] == 72.0


def test_the_interval_covers_the_true_quantile_as_often_as_it_says():
    rng, hits, sims = random.Random(0), 0, 2000
    for _ in range(sims):
        _, lo, hi = budget.quantile_ci([rng.expovariate(1.0) for _ in range(80)], 0.9)
        true = 2.302585  # the 90th percentile of an exponential with rate 1
        hits += lo <= true <= hi
    assert 0.94 <= hits / sims <= 0.99  # order statistics cover at least the level


@pytest.mark.parametrize("q, level", [(0.0, 0.95), (1.0, 0.95), (0.5, 1.0)])
def test_bad_quantiles_are_refused(q, level):
    with pytest.raises(ValueError):
        budget.quantile_ci([1.0, 2.0], q, level)


def test_a_cost_over_its_limit_is_over():
    b = budget.check([0.02, 0.04], [], 0, cost_limit=0.025)
    assert b.outcome == "over" and b.cost_per_run == pytest.approx(0.03)
    assert "cost $0.0300 per run > $0.025" in b.over[0]


def test_latency_blocks_only_when_its_interval_lies_above_the_limit():
    slow = [10.0 + i / 100 for i in range(100)]
    assert budget.check([], slow, 0, latency_limit=9.0).outcome == "over"
    assert (
        budget.check([], slow, 0, latency_limit=10.95).outcome == "within"
    )  # the limit is inside the interval
    few = budget.check(
        [], [10.0, 11.0, 12.0], 0, latency_limit=1.0
    )  # three runs: a lower end, no upper one
    assert few.latency_ci == (11.0, None) and few.outcome == "over"
    one = budget.check([], [12.0], 0, latency_limit=1.0)  # one run bounds nothing
    assert one.latency_ci == (None, None) and one.outcome == "within"


def test_retries_are_counted_and_limits_checked():
    assert budget.check([0.01], [1.0], 3).retried == 3
    with pytest.raises(ValueError):
        budget.check([0.01], [1.0], 0, cost_limit=-1)


def prices(tmp_path):
    path = tmp_path / "prices.yaml"
    path.write_text("gpt-4.1-mini: [0.40, 1.60]\n")
    return path


def test_the_gate_fails_a_budget_only_when_quality_passed(
    tmp_path, monkeypatch, capsys
):
    base = runs(tmp_path, monkeypatch, "base", 0, Fixed())
    same = runs(tmp_path, monkeypatch, "same", 1, Fixed())
    broken = runs(tmp_path, monkeypatch, "broken", 1, Fixed(total="21.50"))
    report, comment = tmp_path / "v.json", tmp_path / "c.md"
    args = [
        "--base",
        str(base),
        "--prices",
        str(prices(tmp_path)),
        "--json",
        str(report),
        "--markdown",
        str(comment),
    ]
    one = (100 * 0.40 + 20 * 1.60) / 1e6
    assert (
        gate.main([*args, "--candidate", str(same), "--max-cost-per-run", str(one / 2)])
        == gate.BUDGET_FAIL
    )
    verdict = json.loads(report.read_text())
    assert (
        verdict["outcome"] == "budget fail" and verdict["budget"]["outcome"] == "over"
    )
    assert verdict["prices_hash"] and "budget fail" in comment.read_text()
    assert (
        gate.main([*args, "--candidate", str(same), "--max-cost-per-run", str(one * 2)])
        == gate.PASS
    )
    assert "Budget of the candidate within" in comment.read_text()
    # quality comes first: a broken candidate is a quality fail even when over budget too
    assert (
        gate.main(
            [*args, "--candidate", str(broken), "--max-cost-per-run", str(one / 2)]
        )
        == gate.QUALITY_FAIL
    )


def test_a_cost_limit_without_prices_is_an_infra_error(tmp_path, monkeypatch, capsys):
    base = runs(tmp_path, monkeypatch, "base", 0, Fixed())
    cand = runs(tmp_path, monkeypatch, "cand", 1, Fixed())
    code = gate.main(
        ["--base", str(base), "--candidate", str(cand), "--max-cost-per-run", "1"]
    )
    assert code == gate.INFRA_ERROR and "needs --prices" in capsys.readouterr().err


def test_the_runner_records_which_price_table_it_used(tmp_path, monkeypatch):
    out = runs(tmp_path, monkeypatch, "base", 0, Fixed())
    assert (
        json.loads(out.read_text().splitlines()[0])["prices_hash"] is None
    )  # no --prices


def test_the_runner_stamps_the_hash_of_its_price_table(tmp_path, monkeypatch):
    from test_gate import GOLDEN, config

    from llm_release_gate import runner
    from llm_release_gate.hashing import canonical_hash

    monkeypatch.setattr(runner, "load_pipeline", lambda c: Fixed())
    out = tmp_path / "runs.jsonl"
    runner.main(["--config", str(config(tmp_path, "b", 0)), "--golden", str(GOLDEN), "--out", str(out),
                 "--prices", str(prices(tmp_path))])  # fmt: skip
    assert json.loads(out.read_text().splitlines()[0])["prices_hash"] == canonical_hash(
        {"gpt-4.1-mini": [0.40, 1.60]}
    )


def exact_ranks(n, q, tail):
    """The interval's ranks from exact binomial sums in fractions: the reference for the float version."""
    from fractions import Fraction
    from math import comb

    q = Fraction(q)
    cdf = [
        sum(comb(n, i) * q**i * (1 - q) ** (n - i) for i in range(k + 1))
        for k in range(n + 1)
    ]
    lo = max((r for r in range(1, n + 1) if cdf[r - 1] <= tail), default=None)
    hi = min((r for r in range(1, n + 1) if 1 - cdf[r - 1] <= tail), default=None)
    return lo, hi


def test_the_ranks_match_exact_arithmetic():
    from fractions import Fraction

    for n in range(1, 61):
        for q in ("0.5", "0.9", "0.95"):
            _, lo, hi = budget.quantile_ci(
                [float(x) for x in range(1, n + 1)], float(q)
            )
            assert (lo, hi) == exact_ranks(n, Fraction(q), Fraction(1, 40)), (n, q)


def test_a_pool_sized_sample_is_fast_and_does_not_overflow():
    import time

    start = time.perf_counter()
    est, lo, hi = budget.quantile_ci([float(x) for x in range(1, 5001)], 0.95)
    assert time.perf_counter() - start < 2 and lo < est < hi


def test_a_limit_the_runs_cannot_decide_says_so(tmp_path, monkeypatch, capsys):
    b = budget.check([], [12.0], 0, latency_limit=1.0)
    assert b.unchecked == ["latency: too few runs for a lower end"]
    assert budget.check([], [], 0, latency_limit=1.0).unchecked == ["latency: no runs"]
    base = runs(tmp_path, monkeypatch, "base", 0, Fixed())
    cand = runs(tmp_path, monkeypatch, "cand", 1, Fixed())
    comment = tmp_path / "c.md"
    args = [
        "--base",
        str(base),
        "--candidate",
        str(cand),
        "--max-latency",
        "0.1",
        "--markdown",
        str(comment),
    ]
    assert (
        gate.main(args) == gate.PASS
    )  # one run of 0.5 s cannot show the 95th percentile above 0.1 s
    assert "not checked: latency: too few runs for a lower end" in comment.read_text()
