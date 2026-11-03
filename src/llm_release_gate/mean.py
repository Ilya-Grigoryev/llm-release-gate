"""The gate's rule on the mean: pass when the candidate is shown to be at most delta worse than the base, block when it
is shown to be more than delta worse, inconclusive otherwise.

Every run k of a case is paired with run k of the base; D = candidate - base lies in [-1, 1] and Y = (D + 1) / 2 in
[0, 1]. Each side is a one-sided betting test (Waudby-Smith and Ramdas, "Estimating means of bounded random variables
by betting", arXiv:2010.09686v7): the capital K+ = prod(1 + lam * (Y - m)) at m = (1 - delta) / 2 passes once it reaches
1 / alpha, K- = prod(1 - lam * (Y - m)) blocks. Ville's inequality bounds the error at alpha over any number of looks,
so runs can be added and the rule run again. The bet lam is the paper's predictable plug-in (Eq. 26), truncated at
c / m and c / (1 - m) (Theorem 3).

Cases have different means, and the paper assumes one. With the bet held fixed for all cases of a run, a run's
expected factor is prod(1 + lam * (mu_i - m)) <= (1 + lam * (mean mu - m)) ** N <= 1 under the null (AM-GM), so the
capital after whole runs is still a supermartingale. Looks are taken after whole runs only.

Units: `case` bets on every case of a run (N bets per run); `run` bets once per run on the run's mean of Y (valid even
if the calls within a run are correlated, but needs about as many runs as `case` needs case runs). `bernstein` is the
paper's empirical-Bernstein process (Theorem 2, Eq. 13-15) in place of the bet. Pure functions: scores in, verdict out.
"""

import itertools
import math
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class MeanVerdict:
    outcome: str  # pass / block / inconclusive
    method: str
    delta: float  # the loss that matters, as a share of the score (0.05 = 5 points)
    alpha: float  # per side
    cases: int
    runs: int  # runs of each version paired; the rule looks after runs min_runs..runs
    decided_at: int | None  # the look that decided
    diff: float  # mean of candidate - base over the paired runs
    lower: float  # bounds on the true difference at the last look, 1 - alpha each side
    upper: float
    worse: bool  # pass, but shown worse than the base: the comment warns (D-004)
    runs_for_pass: (
        int | None
    )  # runs of each version a candidate identical to the base needs to pass; None: never


def _check(
    base: Mapping[str, Sequence[float]], candidate: Mapping[str, Sequence[float]]
) -> None:
    if base.keys() != candidate.keys() or not base:
        raise ValueError("the arms must score the same, non-empty set of cases")
    for arm in (base, candidate):
        for case, runs in arm.items():
            if not runs:
                raise ValueError(f"{case}: no runs")
            if any(isinstance(v, bool) or not 0 <= v <= 1 for v in runs):
                raise ValueError(f"{case}: scores outside [0, 1]")


def observations(
    base: Mapping[str, Sequence[float]], candidate: Mapping[str, Sequence[float]]
) -> list[list[float]]:
    """Y per paired run, cases in id order: [run][case]. Runs beyond the shorter arm or case are left out."""
    _check(base, candidate)
    cases = sorted(base)
    k = min(len(arm[c]) for arm in (base, candidate) for c in cases)
    return [[(candidate[c][r] - base[c][r] + 1) / 2 for c in cases] for r in range(k)]


def _bet(var: float, t: int, alpha: float) -> float:
    """Eq. 26: the predictable plug-in bet for the t-th observation, from the variance estimate of the first t - 1."""
    return math.sqrt(2 * math.log(2 / alpha) / (var * t * math.log(t + 1)))


def _psi(lam: float) -> float:
    return (-math.log(1 - lam) - lam) / 4


def _steps(
    rounds: Iterable[Sequence[float]],
    m: float,
    alpha: float,
    unit: str,
    bet: str,
    c: float,
) -> Iterator[tuple[float, float]]:
    if unit not in ("case", "run") or bet not in ("betting", "bernstein"):
        raise ValueError(f"unknown method {unit}/{bet}")
    if not 0 < m < 1 or not 0 < c < 1:
        raise ValueError("need 0 < m < 1 and 0 < c < 1")
    t, total, sq = (
        0,
        0.0,
        0.0,
    )  # observations so far, their sum, sum of (x_i - mean_i) ** 2
    up = down = 0.0
    for r in rounds:
        xs = list(r) if unit == "case" else [sum(r) / len(r)]
        lam = _bet((0.25 + sq) / (t + 1), t + 1, alpha)
        if bet == "betting":
            lp, lm = min(lam, c / m), min(lam, c / (1 - m))
            up += sum(math.log1p(lp * (x - m)) for x in xs)
            down += sum(math.log1p(-lm * (x - m)) for x in xs)
        else:
            lam, mu = min(lam, c), (0.5 + total) / (t + 1)
            v = sum(4 * (x - mu) ** 2 for x in xs) * _psi(lam)
            up += lam * sum(x - m for x in xs) - v
            down += lam * sum(m - x for x in xs) - v
        for x in xs:
            t += 1
            total += x
            sq += (x - (0.5 + total) / (t + 1)) ** 2
        yield up, down


def capitals(
    ys: Sequence[Sequence[float]],
    m: float,
    alpha: float,
    unit: str = "case",
    bet: str = "betting",
    c: float = 0.5,
) -> list[tuple[float, float]]:
    """log K+ and log K- at threshold m after each whole run.

    The bet and, for `bernstein`, the mean in its variance term are those the paper gives for the first observation of
    a run, held for the whole run.
    """
    return list(_steps(ys, m, alpha, unit, bet, c))


def _bound(ys: Sequence[Sequence[float]], alpha: float, side: int, **method) -> float:
    """The difference at which the last look's capital crosses 1 / alpha: lower bound (side +1) or upper (-1)."""
    goal = math.log(1 / alpha)

    def rejected(m: float) -> bool:
        return capitals(ys, m, alpha, **method)[-1][0 if side > 0 else 1] >= goal

    lo, hi = 1e-9, 1 - 1e-9
    if side > 0 and not rejected(lo):
        return -1.0
    if side < 0 and not rejected(hi):
        return 1.0
    for _ in range(50):  # K+ falls and K- rises with m
        mid = (lo + hi) / 2
        if rejected(mid) == (side > 0):
            lo = mid
        else:
            hi = mid
    return 2 * (lo if side > 0 else hi) - 1


def runs_for_pass(
    cases: int,
    delta: float,
    alpha: float,
    unit: str = "case",
    bet: str = "betting",
    c: float = 0.5,
    cap: int = 10_000,
) -> int | None:
    """Runs of each version a candidate that never differs from the base needs to pass; None if more than `cap`."""
    silent = itertools.repeat([0.5] * cases, cap)
    for k, (up, _) in enumerate(
        _steps(silent, (1 - delta) / 2, alpha, unit, bet, c), start=1
    ):
        if up >= math.log(1 / alpha):
            return k
    return None


def first(
    steps: Sequence[tuple[float, float]], alpha: float, min_runs: int = 2
) -> tuple[str, int | None]:
    """The outcome at the first look from `min_runs` on at which either side reaches 1 / alpha; block wins a tie."""
    goal = math.log(1 / alpha)
    for k, (up, down) in enumerate(steps, start=1):
        if k >= min_runs and max(up, down) >= goal:
            return ("block" if down >= goal else "pass"), k
    return "inconclusive", None


def decide(
    base: Mapping[str, Sequence[float]],
    candidate: Mapping[str, Sequence[float]],
    delta: float,
    alpha: float = 0.025,
    unit: str = "case",
    bet: str = "betting",
    c: float = 0.5,
    min_runs: int = 2,
) -> MeanVerdict:
    """The rule on the scores of each case over the runs of both versions (`first` decides)."""
    if not 0 < delta < 1 or not 0 < alpha < 0.5:
        raise ValueError("need 0 < delta < 1 and 0 < alpha < 0.5")
    ys = observations(base, candidate)
    method = {"unit": unit, "bet": bet, "c": c}
    name = f"{bet} on {'case runs' if unit == 'case' else 'runs'}, c {c:g}"
    outcome, at = first(capitals(ys, (1 - delta) / 2, alpha, **method), alpha, min_runs)
    lower, upper = _bound(ys, alpha, +1, **method), _bound(ys, alpha, -1, **method)
    need = runs_for_pass(len(base), delta, alpha, **method)
    diff = sum(2 * y - 1 for r in ys for y in r) / sum(len(r) for r in ys)
    return MeanVerdict(
        outcome,
        name,
        delta,
        alpha,
        len(base),
        len(ys),
        at,
        diff,
        lower,
        upper,
        outcome == "pass" and upper < 0,
        None if need is None else max(min_runs, need),
    )
