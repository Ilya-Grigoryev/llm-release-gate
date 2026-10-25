"""Cost and latency budgets of the candidate: pure functions over its runs, no files, network or clock.

Cost: the mean USD per run (the gate's price table) against a limit, without an interval for now.
Latency: a quantile of the per-run latency with an interval from order statistics, which assumes independent runs and
nothing about their distribution; K repetitions of one case are not independent, so with K > 1 the interval is
optimistic. A run's latency is the time of the attempt that answered: backoff and failed attempts are not in it, and runs
that needed retries are counted apart. The budget blocks only when a limit is clearly exceeded: the mean cost is above
its limit, or the lower end of the latency interval is.
"""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Budget:
    outcome: str  # within / over
    over: list[str]  # the limits exceeded
    unchecked: list[str]  # limits the runs could not decide, and why
    runs: int
    retried: int  # runs that needed a retry
    cost_per_run: float | None
    cost_limit: float | None
    latency_q: float
    latency_s: float | None  # the sample quantile
    # None where there are too few runs for that end
    latency_ci: tuple[float | None, float | None]
    latency_limit: float | None
    level: float


def binom_cdfs(n: int, p: float) -> list[float]:
    """P(B <= k) for B ~ Binomial(n, p), k = 0..n, summed from log-probabilities: linear in n, no huge integers."""
    lp, lq, lf = math.log(p), math.log1p(-p), math.lgamma(n + 1)
    out, total = [], 0.0
    for k in range(n + 1):
        total += math.exp(
            lf - math.lgamma(k + 1) - math.lgamma(n - k + 1) + k * lp + (n - k) * lq
        )
        out.append(min(total, 1.0))
    return out


def quantile_ci(
    values: list[float], q: float, level: float = 0.95
) -> tuple[float, float | None, float | None]:
    """The q-quantile of `values` and a two-sided `level` interval from order statistics.

    An end is None when there are too few values for it (the upper end of a 95th percentile needs n >= 72).
    """
    if not values:
        raise ValueError("no values")
    if not 0 < q < 1 or not 0 < level < 1:
        raise ValueError("q and level must lie in (0, 1)")
    xs, n = sorted(values), len(values)
    estimate = xs[min(n - 1, max(0, math.ceil(q * n) - 1))]
    tail, cdf = (1 - level) / 2, binom_cdfs(n, q)
    # lower end: the largest rank l with P(fewer than l values below the quantile) <= tail
    lo = max((r for r in range(1, n + 1) if cdf[r - 1] <= tail), default=None)
    # upper end: the smallest rank u with P(at least u values below the quantile) <= tail
    hi = min((r for r in range(1, n + 1) if 1 - cdf[r - 1] <= tail), default=None)
    return estimate, (xs[lo - 1] if lo else None), (xs[hi - 1] if hi else None)


def check(
    costs: list[float],
    latencies: list[float],
    retried: int,
    *,
    cost_limit: float | None = None,
    latency_limit: float | None = None,
    latency_q: float = 0.95,
    level: float = 0.95,
) -> Budget:
    """The candidate's budget verdict. `costs` and `latencies` are per run; a limit left out is not checked."""
    for name, limit in (("cost", cost_limit), ("latency", latency_limit)):
        if limit is not None and (not math.isfinite(limit) or limit < 0):
            raise ValueError(f"{name} limit must be a finite number >= 0, got {limit}")
    over, unchecked = [], []
    cost = sum(costs) / len(costs) if costs else None
    if cost_limit is not None:
        if cost is None:
            unchecked.append("cost: no runs")
        elif cost > cost_limit:
            over.append(f"cost ${cost:.4f} per run > ${cost_limit:g}")
    estimate = lo = hi = None
    if latencies:
        estimate, lo, hi = quantile_ci(latencies, latency_q, level)
    if latency_limit is not None:
        if lo is None:
            unchecked.append(
                f"latency: {'no runs' if not latencies else 'too few runs for a lower end'}"
            )
        elif lo > latency_limit:
            over.append(
                f"latency p{100 * latency_q:g} {estimate:.2f} s (lower end {lo:.2f} s) > {latency_limit:g} s"
            )
    return Budget(
        "over" if over else "within",
        over,
        unchecked,
        max(len(costs), len(latencies)),
        retried,
        cost,
        cost_limit,
        latency_q,
        estimate,
        (lo, hi),
        latency_limit,
        level,
    )
