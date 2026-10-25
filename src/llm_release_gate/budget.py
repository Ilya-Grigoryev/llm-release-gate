"""Cost and latency budgets of the candidate: pure functions over its runs, no files, network or clock.

Cost: the mean USD per run (the gate's price table) against a limit; tokens vary little, so no interval.
Latency: a quantile of the per-run latency with a distribution-free interval from order statistics. A run's latency is
the time of the attempt that answered: backoff and failed attempts are not in it, and runs that needed retries are
counted apart. The budget blocks only when a limit is clearly exceeded: the mean cost is above its limit, or the lower
end of the latency interval is.
"""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Budget:
    outcome: str  # within / over
    over: list[str]  # the limits exceeded
    runs: int
    retried: int  # runs that needed a retry
    cost_per_run: float | None
    cost_limit: float | None
    latency_q: float
    latency_s: float | None  # the sample quantile
    latency_ci: tuple[
        float | None, float | None
    ]  # None where n is too small for that end
    latency_limit: float | None
    level: float


def binom_cdf(k: int, n: int, p: float) -> float:
    return sum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k + 1))


def quantile_ci(
    values: list[float], q: float, level: float = 0.95
) -> tuple[float, float | None, float | None]:
    """The q-quantile of `values` and a two-sided `level` interval from order statistics (any continuous distribution).

    An end is None when there are too few values for it (the upper end of a 95th percentile needs n >= 72).
    """
    if not values:
        raise ValueError("no values")
    if not 0 < q < 1 or not 0 < level < 1:
        raise ValueError("q and level must lie in (0, 1)")
    xs, n = sorted(values), len(values)
    estimate = xs[min(n - 1, max(0, math.ceil(q * n) - 1))]
    tail = (1 - level) / 2
    # lower end: the largest rank l with P(fewer than l values below the quantile) <= tail
    lo = max(
        (r for r in range(1, n + 1) if binom_cdf(r - 1, n, q) <= tail), default=None
    )
    # upper end: the smallest rank u with P(at least u values below the quantile) <= tail
    hi = min(
        (r for r in range(1, n + 1) if 1 - binom_cdf(r - 1, n, q) <= tail), default=None
    )
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
    over = []
    cost = sum(costs) / len(costs) if costs else None
    if cost_limit is not None and cost is not None and cost > cost_limit:
        over.append(f"cost ${cost:.4f} per run > ${cost_limit:g}")
    estimate = lo = hi = None
    if latencies:
        estimate, lo, hi = quantile_ci(latencies, latency_q, level)
    if latency_limit is not None and lo is not None and lo > latency_limit:
        over.append(
            f"latency p{100 * latency_q:g} {estimate:.2f} s (lower end {lo:.2f} s) > {latency_limit:g} s"
        )
    return Budget(
        "over" if over else "within",
        over,
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
