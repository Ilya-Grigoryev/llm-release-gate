"""The gate's rule on checks (D-003, D-030): a check that breaks consistently blocks, whatever the mean does.

Pure functions: the result of each (case, check) in every run of both versions in, a verdict out. `whole_runs` is the
gate's rule, a permutation test over whole runs. A run holds every check of every case at one repetition, so checks
that fail together stay together. The test deals the runs of both versions out again, in every way or in 1999 random
ways besides the real one, and asks how often some check looks as much worse as it does under the real labels:
one-sided Fisher p per check, the smallest over the checks, step-down (Westfall and Young). `per_check` is the rule it
replaced, Fisher per check with Tarone's correction: at 5 + 5 runs it blocks none of 7 or more checks broken in every
run (experiment E-008); experiments E-009 and E-010 compare the two.
"""

import bisect
import itertools
import math
import random
from dataclasses import dataclass
from fractions import Fraction
from functools import cache
from typing import Any

Key = tuple[str, str]  # (case, check)
EXHAUSTIVE = 2000  # every split up to this many (6 + 6 runs give 924); beyond, the real one and SPLITS random ones
SPLITS = 1999
MAX_RUNS = 10  # runs of each version `whole_runs` reads: experiment E-009 checked the test up to 10 + 10


@dataclass(frozen=True)
class Unit:
    case: str
    check: str
    base: tuple[int, int]  # passes, runs
    candidate: tuple[int, int]
    p: float  # Fisher: the check got worse (one-sided) or changed (two-sided)
    p_min: float  # the smallest p its run counts allow
    adjusted: float | None = None  # `whole_runs`: permutation p, step-down


@dataclass(frozen=True)
class CheckVerdict:
    outcome: str  # pass / block / report (would block, but the mode only reports)
    mode: str
    alpha: float
    runs: tuple[int, int]  # runs of the base and of the candidate the test read
    cut: bool  # runs past MAX_RUNS were left out
    splits: int  # splits of the runs between the versions, the real one included
    seed: int  # of the random splits; unused when the test took every split
    broken: list[
        Unit
    ]  # named: adjusted p at most alpha and fewer passes; smallest adjusted p first
    units: list[Unit]  # every check both versions scored, smallest adjusted p first
    one_sided: list[
        Key
    ]  # checks scored in one version only: in the splits, never named


@dataclass(frozen=True)
class TaroneVerdict:
    outcome: str
    mode: str
    alpha: float
    sides: int
    m: int  # Tarone's number of tests
    testable: int  # checks whose run counts could reach the corrected threshold; 0 also when nothing changed
    broken: list[Unit]  # worse beyond the corrected threshold, smallest p first
    units: list[Unit]  # every check both versions scored, smallest p first
    one_sided: list[Key]  # checks scored in one version only: left out of the test


def passed(value: Any, threshold: float) -> bool | None:
    """A check's result as pass or fail: a share passes at `threshold` or above; None stays unscored."""
    if value is None or isinstance(value, bool):
        return value
    return value >= threshold


def pmfs(kb: int, kc: int, total: int) -> list[Fraction]:
    """P(the candidate has i passes | `total` passes over both versions), i = 0..kc: Fisher's hypergeometric, exactly."""
    whole = math.comb(kb + kc, total)
    return [Fraction(math.comb(kc, i) * math.comb(kb, total - i), whole) if 0 <= total - i <= kb else Fraction(0)
            for i in range(kc + 1)]  # fmt: skip


def fisher(x: int, kb: int, y: int, kc: int, sides: int) -> tuple[Fraction, Fraction]:
    """p and the smallest attainable p for `y` of `kc` candidate passes against `x` of `kb` base passes.

    Exact fractions: a p of exactly alpha (5 of 5 against 0 of 5 is 1/252) must not fall on the wrong side of it.
    """
    pr = pmfs(kb, kc, x + y)
    support = [i for i, v in enumerate(pr) if v > 0]
    if sides == 1:  # the candidate passes less often
        return sum(pr[: y + 1], Fraction(0)), pr[support[0]]

    def two(i):  # every table at most as likely as this one
        return sum((v for v in pr if v <= pr[i]), Fraction(0))

    return two(y), min(two(i) for i in support)


def per_check(
    base: dict[Key, list[Any]],
    candidate: dict[Key, list[Any]],
    *,
    alpha: float = 0.025,
    sides: int = 1,
    mode: str = "block",
    threshold: float = 1.0,
) -> TaroneVerdict:
    """Tarone's rule: test every (case, check) that both versions scored; block if one is significantly worse after the
    correction.

    The lists hold one result per repetition: True / False, a share in [0, 1] (passes at `threshold`, one for the whole
    call: a case with its own threshold turns its shares into True / False first) or None (not scored, left out). A
    two-sided test blocks only on a check that got worse.
    """
    if base.keys() != candidate.keys() or not base:
        raise ValueError(
            "the versions must have the same, non-empty set of (case, check)"
        )
    if not 0 < alpha < 1 or sides not in (1, 2) or mode not in ("block", "report"):
        raise ValueError(
            "alpha must lie in (0, 1), sides be 1 or 2, mode block or report"
        )
    units, exact, one_sided = [], {}, []
    a = Fraction(str(alpha))  # 0.025 as 1/40, not the float next to it
    for key in sorted(base):
        b = [v for v in (passed(x, threshold) for x in base[key]) if v is not None]
        c = [v for v in (passed(x, threshold) for x in candidate[key]) if v is not None]
        if not b or not c:
            if b or c:
                one_sided.append(key)
            continue
        x, y = sum(b), sum(c)
        p, p_min = fisher(x, len(b), y, len(c), sides)
        unit = Unit(key[0], key[1], (x, len(b)), (y, len(c)), float(p), float(p_min))
        units.append(unit)
        exact[key] = p, p_min
    p_mins = sorted(pm for _, pm in exact.values())
    m = 1  # Tarone: the smallest m with at most m checks whose smallest p can reach alpha / m
    while bisect.bisect_right(p_mins, a / m) > m:
        m += 1
    testable = [u for u in units if exact[u.case, u.check][1] <= a / m]
    broken = [
        u
        for u in testable
        if exact[u.case, u.check][0] <= a / m
        and u.candidate[0] * u.base[1] < u.base[0] * u.candidate[1]
    ]
    broken.sort(key=lambda u: u.p)
    outcome = "pass" if not broken else mode if mode == "report" else "block"
    return TaroneVerdict(
        outcome,
        mode,
        alpha,
        sides,
        m,
        len(testable),
        broken,
        sorted(units, key=lambda u: u.p),
        one_sided,
    )


def floor(kb: int, kc: int) -> Fraction:
    """The smallest adjusted p `whole_runs` can give with these run counts: one split of all of them, or the real one
    of the random ones."""
    kb, kc = min(kb, MAX_RUNS), min(kc, MAX_RUNS)
    n = math.comb(kb + kc, kb)
    return Fraction(1, n if n <= EXHAUSTIVE else SPLITS + 1)


def can_block(kb: int, kc: int, alpha: float = 0.025) -> bool:
    """Whether a check that passed in all `kb` base runs and failed in all `kc` candidate runs can block."""
    if not 0 < alpha < 1:
        raise ValueError("alpha must lie in (0, 1)")
    return floor(kb, kc) <= Fraction(str(alpha))


def weak(kb: int, kc: int, alpha: float = 0.025) -> bool:
    """Whether a block needs every other split to look less bad: one check that varies in another pattern then stops a
    break from blocking (4 + 4 runs at 0.025)."""
    return can_block(kb, kc, alpha) and 2 * floor(kb, kc) > Fraction(str(alpha))


def runs_to_block(alpha: float = 0.025) -> int | None:
    """The fewest runs of each version from which a check broken in every run can block; None if no number up to
    MAX_RUNS can."""
    return next((k for k in range(1, MAX_RUNS + 1) if can_block(k, k, alpha)), None)


def splits(kb: int, kc: int, seed: int = 0) -> list[int]:
    """Splits of `kb` + `kc` runs between the versions, each a bit mask of the runs labelled base; the real one (runs 0
    to kb − 1) first. All of them up to EXHAUSTIVE, else SPLITS random ones besides the real one."""
    n = kb + kc
    if math.comb(n, kb) <= EXHAUSTIVE:
        return [sum(1 << i for i in s) for s in itertools.combinations(range(n), kb)]
    rng = random.Random(seed)
    return [(1 << kb) - 1] + [
        sum(1 << i for i in rng.sample(range(n), kb)) for _ in range(SPLITS)
    ]


@cache
def worse(x: int, kb: int, y: int, kc: int) -> float:
    """One-sided Fisher p, exact and then rounded: equal fractions give equal floats, and distinct ones over at most
    20 runs lie far apart, so comparing the floats compares the fractions."""
    return float(fisher(x, kb, y, kc, 1)[0])


def adjusted(rows: list[tuple[int, int]], masks: list[int]) -> list[Fraction]:
    """Step-down minP (Westfall and Young) over checks given as bit masks (runs passed, runs scored); masks[0] is the
    real split. Ranked by their p under the real split, check j gets the share of splits in which some check ranked
    from j on has a p at most j's real one; then the largest such share up to j. In the order of `rows`."""
    kinds = list(
        dict.fromkeys(rows)
    )  # checks with one pattern have one p in every split
    kind = {r: i for i, r in enumerate(kinds)}

    def ps(mask: int) -> list[float]:
        return [
            worse((p & mask).bit_count(), (s & mask).bit_count(), (p & ~mask).bit_count(), (s & ~mask).bit_count())
            for p, s in kinds
        ]  # fmt: skip

    real = ps(masks[0])
    order = sorted(range(len(rows)), key=lambda i: real[kind[rows[i]]])
    ranked = [kind[rows[i]] for i in order]
    bar = [real[k] for k in ranked]
    hits = [0] * len(rows)
    for mask in masks:
        p, low = ps(mask), 2.0
        for j in range(len(ranked) - 1, -1, -1):
            low = min(low, p[ranked[j]])
            hits[j] += low <= bar[j]
    out, top = [Fraction(0)] * len(rows), Fraction(0)
    for j, i in enumerate(order):
        top = max(top, Fraction(hits[j], len(masks)))
        out[i] = top
    return out


def whole_runs(
    base: dict[Key, list[Any]],
    candidate: dict[Key, list[Any]],
    *,
    alpha: float = 0.025,
    mode: str = "block",
    threshold: float = 1.0,
    seed: int = 0,
) -> CheckVerdict:
    """The permutation test over whole runs (D-030): block if some check is significantly worse.

    Run i of a version is position i of every list (True / False, a share that passes at `threshold`, or None: not
    scored); shorter lists end in None, and an unscored result moves with its run. The test reads the first MAX_RUNS
    runs of each version. A check is named when its adjusted p is at most alpha and the candidate passed it less often.
    """
    if base.keys() != candidate.keys() or not base:
        raise ValueError(
            "the versions must have the same, non-empty set of (case, check)"
        )
    if not 0 < alpha < 1 or mode not in ("block", "report"):
        raise ValueError("alpha must lie in (0, 1), mode be block or report")
    arms = [
        {k: [passed(x, threshold) for x in v[:MAX_RUNS]] for k, v in arm.items()}
        for arm in (base, candidate)
    ]
    kb, kc = (max(map(len, arm.values())) for arm in arms)
    cut = any(len(v) > MAX_RUNS for arm in (base, candidate) for v in arm.values())
    found, one_sided, live, rows = {}, [], [], []
    for key in sorted(base):
        b, c = (
            arm[key] + [None] * (k - len(arm[key])) for arm, k in zip(arms, (kb, kc))
        )
        run = b + c
        scored = sum(1 << i for i, v in enumerate(run) if v is not None)
        passes = sum(1 << i for i, v in enumerate(run) if v)
        if 0 < passes.bit_count() < scored.bit_count():  # the same in every split
            live.append(key)
            rows.append((passes, scored))
        b, c = [v for v in b if v is not None], [v for v in c if v is not None]
        if not b or not c:
            if b or c:
                one_sided.append(key)
            continue
        found[key] = (sum(b), len(b)), (sum(c), len(c))
    masks = splits(kb, kc, seed)
    q = dict(zip(live, adjusted(rows, masks) if rows else []))
    a = Fraction(str(alpha))
    units, broken = [], []
    for key, ((x, nb), (y, nc)) in found.items():
        p, p_min = fisher(x, nb, y, nc, 1)
        unit = Unit(
            *key, (x, nb), (y, nc), float(p), float(p_min), float(q.get(key, 1))
        )
        units.append(unit)
        if q.get(key, 1) <= a and y * nb < x * nc:
            broken.append(unit)
    units.sort(key=lambda u: (u.adjusted, u.p))
    broken.sort(key=lambda u: (u.adjusted, u.p))
    outcome = "pass" if not broken else mode
    return CheckVerdict(
        outcome, mode, alpha, (kb, kc), cut, len(masks), seed, broken, units, one_sided
    )
