"""The gate's rule on checks (D-003): a check that breaks consistently blocks, whatever the mean does.

Pure functions: the outcomes of each (case, check) over the repetitions of both versions in, a verdict out. A check is
tested with Fisher's exact test on k of K passes in each version; Tarone's correction counts only the checks that could
reach significance at all (Tarone 1990), and Bonferroni over those controls the chance of any false block. The
correction, the sidedness and alpha are D-003's open choices (M-12), and a list by a discrete BH is not built; the
default, one-sided at 0.025, spends the same false-block budget as the two-sided test at 0.05 that experiment E-002
measured.
"""

import bisect
import math
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

Key = tuple[str, str]  # (case, check)


@dataclass(frozen=True)
class Unit:
    case: str
    check: str
    base: tuple[int, int]  # passes, runs
    candidate: tuple[int, int]
    p: float  # the check got worse (one-sided) or changed (two-sided)
    p_min: float  # the smallest p its run counts allow


@dataclass(frozen=True)
class CheckVerdict:
    outcome: str  # pass / block / report (would block, but the mode only reports)
    mode: str
    alpha: float
    sides: int
    m: int  # Tarone's number of tests
    testable: int  # 0: with these run counts the rule cannot block at all, and the report must say so (D-015)
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
) -> CheckVerdict:
    """Test every (case, check) that both versions scored; block if one is significantly worse after the correction.

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
    return CheckVerdict(
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
