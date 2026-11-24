"""The gate: a rule on the mean (naive: first run per version, a fixed threshold; or betting over all runs) and the rule
on checks (all runs)."""

import argparse
import json
import math
import os
import sys
import traceback
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, replace
from fractions import Fraction
from pathlib import Path

from llm_release_gate import budget, criterion, levels, mean
from llm_release_gate.compare import Arm, Mismatch, load_arm, pair
from llm_release_gate.golden import load_cases, validate
from llm_release_gate.hashing import canonical_hash
from llm_release_gate.metrics import VERSION, score
from llm_release_gate.prices import Prices, load_prices, usd
from llm_release_gate.trace import usage

# Exit codes. 1 and 2 stay with Python and argparse, so a crash is never read as a verdict.
PASS, QUALITY_FAIL, INCONCLUSIVE, BUDGET_FAIL, INFRA_ERROR = 0, 10, 11, 12, 20
VERDICTS = {
    PASS: "pass",
    QUALITY_FAIL: "quality fail",
    INCONCLUSIVE: "inconclusive",
    BUDGET_FAIL: "budget fail",
}


@dataclass(frozen=True)
class Verdict:
    outcome: str  # pass / quality fail / budget fail (quality passed, a budget did not)
    exit_code: int
    base_mean: float
    candidate_mean: float
    diff_pp: float  # candidate minus base, percentage points of the mean score
    limit_pp: float  # the drop that blocks, after a relative threshold is applied
    rule: str
    cases: int
    worse: list[tuple[str, float, float]]  # (case, base, candidate), largest drop first
    runs: int = 1  # runs of each version the rule on the mean read


@dataclass(frozen=True)
class Levelled:
    """What the levels (D-028) add to a verdict."""

    rules: levels.Levels
    reported: (
        criterion.CheckVerdict | None
    )  # minor checks, and normal ones under `checks: report`
    minor_cases: list[str]  # only minor checks: out of the mean
    unmatched: list[str]  # patterns that match no check of the set

    def warnings(self) -> list[criterion.Unit]:
        """Checks that only report and got significantly worse: minor, and normal under `checks: report` (D-028 B)."""
        return list(self.reported.broken) if self.reported else []


def exact(value: float) -> Fraction:
    """Scores are shares of fields, so 0.95 means 19/20, not the float next to it."""
    return Fraction(value).limit_denominator(10**6)


def naive(
    base: dict[str, float],
    candidate: dict[str, float],
    threshold_pp: float,
    relative: bool = False,
) -> Verdict:
    """Compare the mean of one score per case and version.

    Absolute: block if the candidate's mean is lower by more than `threshold_pp` points.
    Relative: the limit is `threshold_pp` percent of the base mean. A drop exactly at the
    limit passes; the means are compared as exact fractions.
    """
    if base.keys() != candidate.keys() or not base:
        raise ValueError("the arms must score the same, non-empty set of cases")
    if not math.isfinite(threshold_pp) or threshold_pp < 0:
        raise ValueError(f"threshold must be a finite number >= 0, got {threshold_pp}")
    out_of_range = sorted(
        {
            k
            for k, v in (*base.items(), *candidate.items())
            if isinstance(v, bool) or not 0 <= v <= 1
        }
    )
    if out_of_range:
        raise ValueError(f"scores outside [0, 1]: {', '.join(out_of_range)}")
    b = sum(map(exact, base.values())) / len(base)
    c = sum(map(exact, candidate.values())) / len(candidate)
    diff = 100 * (c - b)
    limit = exact(threshold_pp) * (b if relative else 1)
    code = QUALITY_FAIL if diff < -limit else PASS
    worse = sorted(
        ((k, base[k], candidate[k]) for k in base if candidate[k] < base[k]),
        key=lambda t: t[2] - t[1],
    )
    unit = "% of the base mean" if relative else "points"
    rule = f"naive rule: block if the mean drops by more than {threshold_pp:g} {unit}"
    return Verdict(
        VERDICTS[code],
        code,
        float(b),
        float(c),
        float(diff),
        float(limit),
        rule,
        len(base),
        worse,
    )


def rescored(arm: Arm, golden: Path) -> Arm:
    """Score every record again from its saved output with the current scorer, without calling the model."""
    set_hash, errors = validate(golden)
    if errors:
        raise Mismatch("; ".join(errors))
    if set_hash != arm.set_hash:
        raise Mismatch(f"{golden} is not the set these runs used")
    cases = {c.id: c for c in load_cases(golden)}
    records = {}
    for key, r in arm.records.items():
        case = cases[r["case"]]
        try:
            result = score(case.expected, r.get("output"), case.scoring, r.get("trace"))
        except Exception as e:  # noqa: BLE001 - one unscorable record must not crash the gate
            records[key] = {
                **r,
                "hits": None,
                "score": None,
                "score_error": f"{type(e).__name__}: {e}",
            }
            continue
        records[key] = {
            **r,
            "hits": result["per_field"],
            "score": result["score"],
            "score_error": None,
        }
    return replace(arm, scorer_version=f"metrics/{VERSION}", records=records)


def first_run(records: list[dict]) -> float:
    """The naive gate looks at one run: the lowest repetition of the case."""
    r = records[0]
    if r.get("score") is None and r.get("score_error"):
        raise Mismatch(
            f"{r['case']}#{r['rep']}: no score ({r['score_error']}); pass --golden to rescore"
        )
    if r.get("score") is None:
        raise Mismatch(f"{r['case']}: no labelled field to score")
    return r["score"]


def all_runs(records: list[dict]) -> list[float]:
    """The scores of every run of a case, lowest repetition first."""
    return [first_run([r]) for r in records]


def betting(
    pairs: dict[str, tuple[list[dict], list[dict]]],
    delta_pp: float,
    method: str,
    alpha: float = 0.025,
) -> tuple[Verdict, mean.MeanVerdict]:
    """The rule on the mean over all runs (D-004 C, D-026 C): pass, block (quality fail) or inconclusive."""
    base = {k: all_runs(b) for k, (b, _) in pairs.items()}
    candidate = {k: all_runs(c) for k, (_, c) in pairs.items()}
    mv = mean.decide(base, candidate, delta_pp / 100, alpha, **mean.METHODS[method])
    code = {"pass": PASS, "block": QUALITY_FAIL, "inconclusive": INCONCLUSIVE}[
        mv.outcome
    ]
    b, c = (
        {k: sum(v[: mv.runs]) / mv.runs for k, v in arm.items()}
        for arm in (base, candidate)
    )
    worse = sorted(
        ((k, b[k], c[k]) for k in b if c[k] < b[k]), key=lambda t: t[2] - t[1]
    )
    rule = (
        f"rule on the mean: pass if shown at most {delta_pp:g} points worse, block if shown more "
        f"({mv.method}, α {mv.alpha:g} each side)"
    )
    v = Verdict(
        VERDICTS[code], code, sum(b.values()) / len(b), sum(c.values()) / len(c), 100 * mv.diff, delta_pp, rule,
        len(b), worse, mv.runs,
    )  # fmt: skip
    return v, mv


def mean_lines(
    mv: mean.MeanVerdict, cost_per_run: float | None, floor: bool = True
) -> list[str]:
    """What the betting rule showed, and what a pass would take (`floor`: the adaptive gate says it in its own lines)."""
    span = f"[{100 * mv.lower:+.1f}, {100 * mv.upper:+.1f}] points ({100 * (1 - 2 * mv.alpha):g} %)"
    shown = f"The difference lies in {span}"
    if mv.outcome != "inconclusive":
        out = [
            f"After run {mv.decided_at} of each version the difference lay in {span}, which decided."
            + (
                " Later runs do not change it."
                if mv.runs > (mv.decided_at or 0)
                else ""
            )
        ]
        if mv.worse:
            out.append("⚠️ Shown worse than the base, but by less than δ.")
        return out
    need = mv.runs_for_pass
    if not floor:
        return [f"{shown}; not decided."]
    if need is None:
        return [
            f"{shown}; not decided. With this method and {mv.cases} case{'s' if mv.cases != 1 else ''} a pass needs more than 10 000 runs."
        ]
    more = max(0, need - mv.runs)
    fewer = (
        "; fewer with a larger `alpha` or δ" if need > 2 else ""
    )  # no look before run 2
    twice = mv.runs_for_pass_twice
    more_cases = (
        f"; with {2 * mv.cases} cases, {twice}"
        if twice is not None and twice < need
        else ""
    )
    floor = (
        f"A pass needs at least {need} runs of each version even if nothing changed "
        f"({mv.cases} case{'s' if mv.cases != 1 else ''}, δ {100 * mv.delta:g} points, α {mv.alpha:g}{fewer}{more_cases})"
    )
    if not more:
        return [
            f"{shown}; not decided. {floor}; these {mv.runs} did not show it: the versions differ, or the noise needs more."
        ]
    price = (
        f", about ${more * cost_per_run:.2f} outside CI (a new CI job runs all {need} afresh)"
        if cost_per_run and more
        else ""
    )
    return [f"{shown}; not decided. {floor}: {more} more{price}."]


def split(alpha: float, checks_block: bool) -> tuple[float, float]:
    """The whole gate's alpha (D-031) as (rule on the mean, rule on checks). Whether a check may block depends on the
    settings and the set's checks, never on the results, so the shares still add up to alpha."""
    return (alpha / 2 if checks_block else alpha), alpha / 2


def may_block(checks: str, rules: levels.Levels) -> bool:
    """Whether a check may block, by the settings alone: `checks: block`, or a critical level."""
    return (
        checks == "block" or bool(rules.critical) or "critical" in rules.cases.values()
    )


MAX_ROUNDS = 60  # the most rounds the adaptive gate buys, as experiment E-011 simulated


def k_c(alpha: float, checks_block: bool) -> int:
    """The round at which the adaptive gate reads the checks, once (D-032): known from the settings before any run. Five,
    or the first round at which a check broken in every run can block when `alpha` is so small that it needs more; two
    when no check may block."""
    if not checks_block:
        return 2
    need = criterion.first_block(split(alpha, True)[1])
    if need is None:
        raise ValueError(
            f"with alpha {alpha:g} no number of rounds lets a check block: raise alpha, or set checks: report"
        )
    return max(5, need)


def plan(
    rounds: int,
    kc: int,
    spent: float,
    limit: float,
    cost_of: Callable[[int], float | None],
) -> int:
    """Rounds to run next in one go; 0: stop, the next round does not fit. `cost_of(j)` estimates round j's cost to this
    job from the last round, None before the candidate's first. A round runs only if its estimate fits in what is left
    of `limit`; with no estimate yet, one round runs to learn it. Up to `kc` the rounds go in one batch, then one at a
    time."""
    target = kc if rounds < kc else rounds + 1
    n, total = 0, spent
    for j in range(rounds + 1, target + 1):
        cost = cost_of(j)
        if cost is None:
            return max(n, 1)
        if total + cost > limit * (1 + 1e-9):
            break
        n, total = n + 1, total + cost
    return n


def complete(arm: Arm, cases: Iterable[str]) -> int:
    """Rounds every case has: the largest r with an error-free run of each case for every repetition below r."""
    reps: dict[str, set[int]] = {}
    for case, rep in arm.records:
        reps.setdefault(case, set()).add(rep)
    cases = list(cases)
    r = 0
    while cases and all(r in reps.get(c, ()) for c in cases):
        r += 1
    return r


def first_rounds(arm: Arm, rounds: int) -> Arm:
    return replace(arm, records={k: r for k, r in arm.records.items() if k[1] < rounds})


def round_cost(arm: Arm, rep: int, prices: Prices) -> float:
    """USD for one round of the arm, reused runs priced too: the estimate of the next."""
    spent = [record_cost(r, prices) for (_, k), r in arm.records.items() if k == rep]
    if None in spent:
        raise ValueError(
            "a model in these runs has no price: max_spend_usd cannot be kept"
        )
    return sum(spent)


def look(
    runs: tuple[dict[criterion.Key, list], dict[criterion.Key, list]],
    rules: levels.Levels,
    mode: str,
    alpha: float,
    rounds: int | None = None,
) -> tuple[criterion.CheckVerdict | None, criterion.CheckVerdict | None]:
    """The rule on checks: one look at runs 1..`rounds` of each version (all if None). The adaptive gate calls it on
    rounds 1..K_c only, so later rounds never give the checks a second look. Returns the checks that may block and,
    with levels, those that only report."""
    if rounds is not None:
        runs = tuple({k: v[:rounds] for k, v in side.items()} for side in runs)
    if rules:
        blocking, reporting = families(runs, rules, mode)
        return (
            criterion.whole_runs(*blocking, alpha=alpha, mode="block")
            if blocking[0]
            else None,
            criterion.whole_runs(*reporting, alpha=alpha, mode="report")
            if reporting[0]
            else None,
        )
    return (
        criterion.whole_runs(*runs, alpha=alpha, mode=mode) if runs[0] else None
    ), None


def adaptive_lines(a: dict) -> list[str]:
    """The adaptive gate's lines (D-032): rounds and money, and why it stopped."""

    def rounds(n: int) -> str:
        return f"{n} round{'s' if n != 1 else ''}"

    left = a["rounds_to_k_c"]
    spent = f"${a['spent_usd']:.2f} of max_spend_usd ${a['max_spend_usd']:g} spent in this job"
    if a["stop"] == "decided":
        return [
            f"{rounds(a['rounds'])} of each version (checks read on rounds 1–{a['k_c']}) · {spent}."
        ]
    if a["stop"] is None:  # the loop buys more; a later comment replaces this one
        return [
            f"{rounds(a['rounds'])} of each version so far · {spent}; buying {a['next_rounds']} more."
        ]
    nxt = (
        ""
        if a["next_round_usd"] is None
        else f"; the next round (about ${a['next_round_usd']:.2f}) does not fit"
    )
    if a["stop"] == "rounds":
        return [
            (
                f"⏸ {rounds(a['rounds'])} of each version, the most the gate buys · {spent}. More rounds will not "
                "settle it: a person decides, or the set needs more cases."
            )
        ]
    out = [f"⏸ {rounds(a['rounds'])} of each version · {spent}{nxt}."]
    if left:
        out.append(
            f"The rule on checks reads rounds 1–{a['k_c']}, so nothing is decided before round {a['k_c']}: {left} more "
            f"round{'s' if left != 1 else ''}, about ${a['to_k_c_usd']:.2f}."
        )
    elif a["pass_rounds"] is None:
        out.append(
            "At the pace so far no pass is in sight: the runs point to a loss near δ or above."
        )
    else:
        more = a["pass_rounds"] - a["rounds"]
        out.append(
            f"A pass needs about {more} more round{'s' if more != 1 else ''} at the pace so far, about "
            f"${a['pass_usd']:.2f} (a forecast)."
        )
    here, twice = (
        None if n is None else max(a["k_c"], n)
        for n in (a["silent_rounds"], a["silent_rounds_twice"])
    )
    if here is not None and twice is not None and twice < here:
        out.append(
            f"More cases would shorten it: with {a['cases']} case{'s' if a['cases'] != 1 else ''} a candidate that "
            f"scores like the base passes at round {here}, with {2 * a['cases']} cases at round {twice}."
        )
    out.append(
        f"Re-run this job to buy up to ${a['max_spend_usd']:g} more; the rounds paid for count."
        if a["resume"] and (a["next_round_usd"] or 0) <= a["max_spend_usd"]
        else f"One round costs more than max_spend_usd ${a['max_spend_usd']:g}: raise it on the target branch."
        if a["resume"]
        else "A re-run of this job starts over, as a new test: it finds none of these runs (no cache directory, no "
        "`actions: read`, or `pull_request_target`). Raise max_spend_usd on the target branch instead."
    )
    return out


def alpha_line(alpha: float, betting: bool, checks_block: bool) -> str:
    """How the gate spends its alpha, for the comment; each rule keeps its share under its own assumptions (docs: How
    often the gate may be wrong)."""
    on_mean, on_checks = split(alpha, checks_block)
    if betting and checks_block:
        return f"False blocks: α {alpha:g} for the gate, {on_mean:g} to the rule on the mean and {on_checks:g} to the rule on checks."
    if betting:
        return f"False blocks: α {alpha:g} for the gate, all of it to the rule on the mean, since no check can block."
    if checks_block:
        return f"False blocks: α {on_checks:g} to the rule on checks; the naive rule on the mean has no α."
    return "False blocks: no check can block, and the naive rule on the mean has no α."


def leveled(
    pairs: dict[str, tuple[list[dict], list[dict]]],
    rules: levels.Levels,
    how: dict[str, str],
) -> tuple[dict[str, tuple[list[dict], list[dict]]], list[str]]:
    """Every run's score without its `minor` checks (D-028), by the case's aggregate in `how`; a case with only `minor`
    checks leaves the mean."""
    if not (rules.minor or rules.cases):
        return pairs, []
    out, minor = {}, []
    for case, arms in pairs.items():
        checks = {k for rs in arms for r in rs for k in r.get("hits") or {}}
        if checks and all(rules.of(case, k) == "minor" for k in checks):
            minor.append(case)
            continue
        out[case] = tuple(
            [r if r.get("hits") is None else {**r, "score": levels.case_score(case, r["hits"], how[case], rules)} for r in rs]
            for rs in arms
        )  # fmt: skip
    if not out:
        raise ValueError("every case is minor: nothing is left for the mean")
    return out, minor


def families(
    runs: tuple[dict[criterion.Key, list], dict[criterion.Key, list]],
    rules: levels.Levels,
    mode: str,
) -> tuple[tuple[dict, dict], tuple[dict, dict]]:
    """The checks that may block (critical; normal under `checks: block`) and those that only report (minor; normal under
    `checks: report`): two families, each with its own alpha (D-028 B)."""

    def blocks(key: criterion.Key) -> bool:
        level = rules.of(*key)
        return level == "critical" or (level == "normal" and mode == "block")

    return tuple(
        tuple({k: v for k, v in side.items() if blocks(k) == want} for side in runs) for want in (True, False)
    )  # fmt: skip


def check_runs(
    pairs: dict[str, tuple[list[dict], list[dict]]],
) -> tuple[dict[criterion.Key, list], dict[criterion.Key, list]]:
    """Per (case, check), its result in every run of the base and of the candidate, at the run's repetition: the test
    over whole runs keeps the cases of one repetition together. A run without results, or missing, gives None."""
    keys = sorted(
        {(case, check) for case, arms in pairs.items() for rs in arms for r in rs for check in r.get("hits") or {}}
    )  # fmt: skip
    reps = {
        (case, side): {r.get("rep", i): r for i, r in enumerate(arms[side])}
        for case, arms in pairs.items()
        for side in (0, 1)
    }
    width = [
        1 + max((k for (_, s), rs in reps.items() if s == side for k in rs), default=-1)
        for side in (0, 1)
    ]
    base, candidate = (
        {
            (case, check): [((reps[case, side].get(i) or {}).get("hits") or {}).get(check) for i in range(width[side])]
            for case, check in keys
        }
        for side in (0, 1)
    )  # fmt: skip
    return base, candidate


def checks_report(
    c: criterion.CheckVerdict, rules: levels.Levels | None = None
) -> dict:
    rules = rules or levels.Levels()
    return {
        "outcome": c.outcome,
        "mode": c.mode,
        "alpha": c.alpha,
        "test": "whole runs",
        "runs": list(c.runs),
        "cut": c.cut,
        "splits": c.splits,
        "seed": c.seed,
        "can_block": bool(c.units) and criterion.can_block(*c.runs, c.alpha, c.seed),
        "weak": criterion.weak(*c.runs, c.alpha, c.seed),
        "runs_to_block": criterion.runs_to_block(c.alpha, c.seed),
        "checked": len(c.units),
        "one_sided": [list(k) for k in c.one_sided],
        "broken": [{**asdict(u), "level": rules.of(u.case, u.check)} for u in c.broken],
    }


def checks_lines(
    c: criterion.CheckVerdict, label: str = "Checks", once: bool = False
) -> tuple[str, list[str]]:
    """The comment's line on the rule on checks, and its table of broken checks (`once`: the adaptive gate read them on
    rounds 1 to K_c and reads no more)."""
    kb, kc = c.runs
    left = (
        f" {len(c.one_sided)} checks scored in one version only are not compared."
        if c.one_sided
        else ""
    )
    if c.cut:
        left += f" The test reads the first {criterion.MAX_RUNS} runs of each version, as far as simulation checked it."
    if not c.units:
        return f"{label}: no check was scored in both versions.{left}", []
    name = f"test over whole runs, α {c.alpha:g}"
    every = math.comb(kb + kc, kb) <= criterion.EXHAUSTIVE
    test = f"{name}, on {kb} + {kc} runs, " + (
        f"all {c.splits} splits"
        if every
        else f"{c.splits - 1} random splits, seed {c.seed}"
    )
    if c.broken:
        verb = (
            (
                "the mode `report` does not block on them"
                if label == "Checks"
                else "they only report"
            )
            if c.outcome == "report"
            else "they block"
        )
        rows = ["", "| Case | Check | Base | Candidate | p |", "|---|---|---|---|---|"]
        rows += [
            f"| {u.case} | {u.check} | {u.base[0]}/{u.base[1]} | {u.candidate[0]}/{u.candidate[1]} | {u.adjusted:.2g} |"
            for u in c.broken[:5]
        ]
        if len(c.broken) > 5:
            rows += ["", f"{len(c.broken) - 5} more in the JSON report."]
        rows += [
            "",
            (
                f"p: the share of the {c.splits} splits of these runs between the versions in which a check looks at "
                f"least this much worse; at most α {c.alpha:g} names it."
            ),
        ]
        return f"{label}: {len(c.broken)} broke, {verb} ({test}).{left}", rows
    worse = sum(
        u.candidate[0] * u.base[1] < u.base[0] * u.candidate[1] for u in c.units
    )
    fewer = f" {worse} of {len(c.units)} passed less often." if worse else ""
    if not criterion.can_block(kb, kc, c.alpha, c.seed):
        need = criterion.runs_to_block(c.alpha, c.seed)
        when = (
            f"a check broken in every run can block {'only ' if once else ''}from {need} runs of each version"
            if need
            else f"at α {c.alpha:g} no number of runs lets a check block"
        )
        head = (
            f"read once, on {kb} + {kc} runs"
            if once  # the adaptive gate reads the checks once, on these runs: more rounds will not change it
            else f"with {kb} + {kc} runs no break can be significant"
        )
        return f"{label}: {head}; {when} ({name}).{fewer}{left}", []
    strong = criterion.runs_to_block(c.alpha, c.seed, strong=True)
    fix = (
        "; a larger `alpha` avoids that"
        if once  # the adaptive gate picks the rounds itself
        else f"; {strong} runs of each version avoid that"
        if strong
        else ""
    )
    which = (  # with random splits, only a pattern one of them drew
        f"in another pattern{' (one fixed in every run too)' if kb == kc else ''}"
        if every
        else f"in a pattern one of the {c.splits - 1} random splits drew"
    )
    soft = (
        f" With {kb} + {kc} runs the rule is weak: any other check that passed in exactly {kb} of the {kb + kc} runs, "
        f"{which}, stops a break from blocking{fix}."
        if criterion.weak(kb, kc, c.alpha, c.seed)
        else ""
    )
    if worse:
        line = f"{label}: none significantly worse; {worse} of {len(c.units)} passed less often ({test}).{soft}{left}"
        return line, []
    return f"{label}: none broke ({len(c.units)} checked, {test}).{soft}{left}", []


def record_cost(r: dict, prices: Prices) -> float | None:
    """USD for one record's calls at the gate's prices; None if a model has no price.

    A record with a trace costs what its model steps cost, the user simulator's included: the price of the decision.
    """
    answered = [
        s
        for s in (r.get("trace") or {}).get("steps", [])
        if s["kind"] == "llm" and s.get("status") == "ok"
    ]
    if answered:  # priced by the gate's table, whatever the runner had
        spent = [
            u["cost_usd"] for u in usage(r["trace"], prices, reprice=True).values()
        ]
        return None if None in spent else sum(spent)
    return usd(r.get("model"), r.get("input_tokens"), r.get("output_tokens"), prices)


def cost(arm: Arm, prices: Prices) -> float | None:
    """USD for the arm's recorded calls, runs reused from an earlier job left out; None if a model has no price."""
    spent = [
        record_cost(r, prices) for r in arm.records.values() if not r.get("reused")
    ]
    return None if None in spent else sum(spent)


def reused(base: Arm, candidate: Arm) -> tuple[int, float | None]:
    """How many base runs came from an earlier job (`pr --cache`), and how many days the oldest ran before the
    candidate's first run."""
    old = replace(
        base, records={k: r for k, r in base.records.items() if r.get("reused")}
    )
    first, last = old.times(), candidate.times()
    if not old.records or not first or not last:
        return len(old.records), None
    return len(old.records), max(0.0, (min(last) - min(first)).total_seconds() / 86400)


def ago(days: float) -> str:
    hours = round(days * 24)
    if days >= 1:
        return f"{days:.1f} days"
    return (
        "less than an hour" if hours < 1 else f"{hours} hour{'s' if hours > 1 else ''}"
    )


def candidate_budget(
    arm: Arm, prices: Prices | None, args: argparse.Namespace
) -> budget.Budget | None:
    """The candidate's budget over its runs, if the command line set a limit."""
    if args.max_cost_per_run is None and args.max_latency is None:
        return None
    runs = list(arm.records.values())
    costs = []
    if args.max_cost_per_run is not None:
        if prices is None:
            raise ValueError("--max-cost-per-run needs --prices")
        costs = [record_cost(r, prices) for r in runs]
        if None in costs:
            raise ValueError(
                "a model in the candidate's runs has no price: the cost limit cannot be checked"
            )
    latencies = [r["latency_s"] for r in runs if r.get("latency_s") is not None]
    return budget.check(
        costs,
        latencies,
        sum(1 for r in runs if r.get("retries")),
        runs=len(runs),
        cost_limit=args.max_cost_per_run,
        latency_limit=args.max_latency,
        latency_q=args.latency_quantile,
    )


def markdown(
    v: Verdict,
    base: Arm,
    candidate: Arm,
    costs: tuple[float | None, float | None] | None = None,
    spend: budget.Budget | None = None,
    checks: criterion.CheckVerdict | None = None,
    mv: mean.MeanVerdict | None = None,
    lv: Levelled | None = None,
    run_cost: float | None = None,  # both versions, one run, reused base runs included
    bound: str | None = None,  # `alpha_line`
    adaptive: dict | None = None,  # the adaptive gate's rounds and money (D-032)
) -> str:
    icon = {
        "pass": "✅",
        "quality fail": "❌",
        "inconclusive": "⚠️",
        "budget fail": "❌",
    }[v.outcome]
    warned = lv.warnings() if lv else []
    critical = [
        u
        for u in (checks.broken if checks and lv else [])
        if lv.rules.of(u.case, u.check) == "critical"
    ]
    lines = [
        f"**Release gate: {icon} {v.outcome}"
        + (
            f" · ⚠️ {len(warned)} {'minor' if all(lv.rules.of(u.case, u.check) == 'minor' for u in warned) else 'reported'}"
            f" check{'s' if len(warned) != 1 else ''} worse"
            if warned
            else ""
        )
        + "**",
        "",
        *(
            [
                "❌ Critical checks broke: "
                + ", ".join(f"`{u.check}` in {u.case}" for u in critical[:5])
                + (f" and {len(critical) - 5} more" if len(critical) > 5 else "")
                + "."
            ]
            if critical
            else []
        ),
        (
            f"Mean score {v.base_mean:.3f} → {v.candidate_mean:.3f} ({v.diff_pp:+.2f} points"
            + (f", blocks below {-v.limit_pp:+.2f}" if mv is None else "")
            + f"); {v.rule}."
        ),
        *(mean_lines(mv, run_cost, adaptive is None) if mv else []),
        *(adaptive_lines(adaptive) if adaptive else []),
        (
            f"{v.cases} cases, {'first run' if mv is None else f'{v.runs} run{"s" if v.runs != 1 else ""}'} of each version · config "
            f"{base.config_hash[:8]} → {candidate.config_hash[:8]} · set {base.set_hash[:8]}"
        ),
        *([bound] if bound else []),
    ]
    line, broken = (
        checks_lines(checks, once=adaptive is not None) if checks else (None, [])
    )
    if line:
        lines.append(line)
    if lv and lv.reported:
        line, more = checks_lines(
            lv.reported,
            "Checks that only report (minor; normal under `checks: report`)",
            once=adaptive is not None,
        )
        lines.append(line)
        broken = [*broken, *more]
    if lv and lv.minor_cases:
        names = ", ".join(lv.minor_cases[:5]) + (
            f" and {len(lv.minor_cases) - 5} more" if len(lv.minor_cases) > 5 else ""
        )
        lines.append(f"Minor cases, out of the mean: {names}.")
    if lv and lv.unmatched:
        lines.append(
            f"⚠️ Levels that match no check of this set: {', '.join(lv.unmatched)}."
        )
    runs, days = reused(base, candidate)
    if runs:
        lines.append(
            f"Base: {runs} of {len(base.records)} runs come from earlier jobs"
            + (
                f"; the oldest ran {ago(days)} before the candidate's."
                if days is not None
                else "."
            )
        )
    aliases = sorted(base.aliases | candidate.aliases)
    if aliases:
        lines.append(
            f"⚠️ Model without a date ({', '.join(aliases)}): the gate takes one name for one model, though the "
            "provider may change it; where both versions asked for the same model, the provider reported the same one."
        )
    if costs and None in costs:
        lines.append("Cost: a model in these runs has no price.")
    elif costs:
        b, c = costs
        lines.append(
            f"Cost of this decision ${b + c:.3f}: base ${b:.3f}, candidate ${c:.3f} "
            f"(successful calls, list prices{'; without the reused base runs' if runs else ''})."
        )
    if spend:
        lines.append(budget_line(spend))
    lines += broken
    if v.worse:
        lines += ["", "| Case | Base | Candidate |", "|---|---|---|"]
        lines += [f"| {k} | {b:.2f} | {c:.2f} |" for k, b, c in v.worse[:5]]
    return "\n".join(lines) + "\n"


def budget_line(spend: budget.Budget) -> str:
    parts = []
    if spend.cost_limit is not None and spend.cost_per_run is not None:
        parts.append(
            f"cost ${spend.cost_per_run:.4f} per run (limit ${spend.cost_limit:g})"
        )
    if spend.latency_limit is not None and spend.latency_s is not None:
        lo, hi = (f"{x:.2f}" if x is not None else "?" for x in spend.latency_ci)
        parts.append(
            f"latency p{100 * spend.latency_q:g} {spend.latency_s:.2f} s "
            f"(interval {lo}–{hi} s; limit {spend.latency_limit:g} s)"
        )
    verdict = (
        "over: " + "; ".join(spend.over) if spend.over else "not shown over its limits"
    )
    if spend.unchecked:
        verdict += " (not checked: " + "; ".join(spend.unchecked) + ")"
    retried = (
        f", {spend.retried} of {spend.runs} runs needed retries"
        if spend.retried
        else ""
    )
    return f"Budget of the candidate {verdict} · {' · '.join(parts)}{retried}."


def alone(
    candidate: Arm, prices: Prices | None, spend: budget.Budget | None
) -> tuple[str, dict]:
    """No base version yet: the candidate's mean score, cost and budget as a comment and a report, for a neutral
    verdict; a budget is reported, not enforced."""
    runs: dict[str, list[dict]] = {}
    for (case, _), r in sorted(candidate.records.items()):
        runs.setdefault(case, []).append(r)
    mean = float(sum(exact(first_run(rs)) for rs in runs.values()) / len(runs))
    spent = cost(candidate, prices) if prices else None
    lines = [
        "**Release gate: 🆕 no base version**",
        "",
        "The target branch has no version of this pipeline yet, so there is nothing to compare with.",
        (
            f"The candidate scores {mean:.3f} on {len(runs)} cases (first run of each) · config "
            f"{candidate.config_hash[:8]} · set {candidate.set_hash[:8]}"
        ),
    ]
    if prices:
        lines.append(
            "Cost: a model in these runs has no price."
            if spent is None
            else f"Cost of these runs ${spent:.3f} (successful calls, list prices)."
        )
    if candidate.aliases:
        lines.append(
            f"⚠️ Model without a date ({', '.join(sorted(candidate.aliases))}): the provider may change it."
        )
    if spend:
        lines.append(
            budget_line(spend)
            + " Without a base version the gate does not block on it."
        )
    report = {
        "outcome": "no base",
        "exit_code": PASS,
        "base_mean": None,
        "candidate_mean": mean,
        "diff_pp": None,
        "base_config": None,
        "candidate_config": candidate.config_hash,
        "set_hash": candidate.set_hash,
        "scorer_version": candidate.scorer_version,
        "cost_usd": {"base": None, "candidate": spent} if prices else None,
        "prices_hash": canonical_hash(prices) if prices else None,
        "budget": asdict(spend) if spend else None,
        "models_without_date": sorted(candidate.aliases),
        "runs_per_case": {"base": 0, "candidate": max(map(len, runs.values()))},
    }
    return "\n".join(lines) + "\n", report


def write_all(files: dict[Path | None, str]) -> None:
    """Write every report or none: a comment must not survive a verdict that failed to save."""
    written = []
    try:
        for path, text in files.items():
            if path:
                path.write_text(text)
                written.append(path)
    except OSError:
        for path in written:
            path.unlink(missing_ok=True)
        raise


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    base = p.add_mutually_exclusive_group(required=True)
    base.add_argument("--base", type=Path, help="runs of the current version (JSONL)")
    base.add_argument(
        "--no-base",
        action="store_true",
        help="no current version yet: report the candidate alone, exit 0",
    )
    p.add_argument(
        "--candidate", type=Path, required=True, help="runs of the new version (JSONL)"
    )
    p.add_argument(
        "--threshold",
        type=float,
        default=5.0,
        help="drop in points that blocks (default 5)",
    )
    p.add_argument(
        "--alpha",
        type=float,
        default=0.05,
        help="how often the gate may block a candidate that is no worse (default 0.05): half to the betting rule "
        "on the mean, half to the rule on checks; the naive rule takes no share",
    )
    p.add_argument(
        "--relative",
        action="store_true",
        help="read --threshold as percent of the base mean",
    )
    p.add_argument(
        "--mean",
        choices=("naive", "betting", *mean.METHODS),
        default="naive",
        help="rule on the mean: naive (first run, block below --threshold) or betting over all runs (pass, block or "
        "inconclusive at δ = --threshold points); other names pick a betting variant (default naive)",
    )
    p.add_argument(
        "--levels",
        type=json.loads,
        help='importance of checks as JSON, e.g. \'{"critical": ["state"], "minor": ["steps"], "cases": {"probe-*": "minor"}}\'',
    )
    p.add_argument(
        "--checks",
        choices=("block", "report"),
        default="block",
        help="a check that broke over the runs blocks, or is only reported (default block)",
    )
    p.add_argument(
        "--golden",
        type=Path,
        help="rescore both versions from their saved answers against this set",
    )
    p.add_argument(
        "--prices",
        type=Path,
        help="YAML `model: [input, output]` or `[input, output, cached input]`, USD per 1M tokens",
    )
    p.add_argument(
        "--max-cost-per-run",
        type=float,
        help="budget: the candidate's mean USD per run (needs --prices)",
    )
    p.add_argument(
        "--max-latency",
        type=float,
        help="budget: seconds for the candidate's latency quantile (blocks if its interval lies above)",
    )
    p.add_argument(
        "--latency-quantile",
        type=float,
        default=0.95,
        help="quantile for --max-latency (default 0.95)",
    )
    p.add_argument(
        "--max-spend",
        type=float,
        help="adaptive runs (needs a betting --mean and --prices): read the rounds both versions finished, the checks "
        "and budgets on rounds 1 to K_c only, and say in the JSON how many rounds fit in this many USD next",
    )
    p.add_argument(
        "--no-resume",
        action="store_true",
        help="with --max-spend: a re-run of the job finds none of these runs, so the comment does not offer one",
    )
    p.add_argument("--json", type=Path, help="write the verdict as JSON")
    p.add_argument("--markdown", type=Path, help="write the merge request comment")
    args = p.parse_args(argv)
    try:
        if not 0 < args.alpha < 0.5:
            raise ValueError(f"alpha must lie in (0, 0.5), got {args.alpha:g}")
        if args.no_base:
            candidate = load_arm(args.candidate)
            if args.golden:
                candidate = rescored(candidate, args.golden)
            prices = load_prices(args.prices) if args.prices else None
            text, report = alone(
                candidate, prices, candidate_budget(candidate, prices, args)
            )
            write_all(
                {args.markdown: text, args.json: json.dumps(report, indent=2) + "\n"}
            )
            print(text, end="")
            return PASS
        base, candidate = load_arm(args.base), load_arm(args.candidate)
        if args.golden:
            base, candidate = (
                rescored(base, args.golden),
                rescored(candidate, args.golden),
            )
        rules = levels.Levels.parse(args.levels)
        whole, adaptive = (base, candidate), None
        if args.max_spend is not None:
            if args.mean == "naive" or not args.prices or not args.max_spend > 0:
                raise ValueError(
                    "--max-spend needs a positive limit, a betting --mean and --prices"
                )
            cases = {c for c, _ in base.records} | {c for c, _ in candidate.records}
            rounds = min(complete(base, cases), complete(candidate, cases))
            if not rounds:
                raise ValueError("no round that every case finished in both versions")
            kc = k_c(args.alpha, may_block(args.checks, rules))
            base, candidate = (
                first_rounds(base, rounds),
                first_rounds(candidate, rounds),
            )
        early = (
            args.max_spend is not None and rounds < kc
        )  # nothing is decided before round K_c
        full = pair(base, candidate)
        if (rules.minor or rules.cases) and not args.golden:
            raise ValueError(
                "levels with minor checks or case levels need --golden: a case's score is rebuilt with its own aggregate"
            )
        how = (
            {c.id: c.scoring.get("aggregate", "mean") for c in load_cases(args.golden)}
            if args.golden
            else {}
        )
        pairs, minor_cases = leveled(full, rules, how)
        runs = check_runs(full)  # minor cases too: their checks warn
        # who may block depends on the settings and the set's checks, never on the results (`split`)
        blocking = (
            families(runs, rules, args.checks)[0]
            if rules
            else runs
            if args.checks == "block"
            else ({}, {})
        )
        on_mean, on_checks = split(args.alpha, bool(blocking[0]))
        mv = None
        if args.mean == "naive":
            v = naive(
                {k: first_run(b) for k, (b, _) in pairs.items()},
                {k: first_run(c) for k, (_, c) in pairs.items()},
                args.threshold,
                args.relative,
            )
        elif args.relative:
            raise ValueError("--relative applies to the naive rule only")
        else:
            v, mv = betting(
                pairs,
                args.threshold,
                mean.DEFAULT if args.mean == "betting" else args.mean,
                on_mean,
            )
        checks, reported = (
            (None, None)
            if early
            else look(
                runs,
                rules,
                args.checks,
                on_checks,
                None if args.max_spend is None else kc,
            )
        )
        lv = (
            Levelled(rules, reported, minor_cases, rules.unmatched(runs[0]))
            if rules
            else None
        )
        if v.exit_code != QUALITY_FAIL and checks and checks.outcome == "block":
            v = replace(v, outcome=VERDICTS[QUALITY_FAIL], exit_code=QUALITY_FAIL)
        if early and v.exit_code != INCONCLUSIVE:
            v = replace(v, outcome=VERDICTS[INCONCLUSIVE], exit_code=INCONCLUSIVE)
            mv = replace(mv, outcome="inconclusive", decided_at=None, worse=False)
        prices = load_prices(args.prices) if args.prices else None
        costs = (cost(whole[0], prices), cost(whole[1], prices)) if prices else None
        spend = (
            None
            if early
            else candidate_budget(
                candidate if args.max_spend is None else first_rounds(candidate, kc),
                prices,
                args,
            )
        )
        if v.exit_code == PASS and spend and spend.outcome == "over":
            v = replace(v, outcome=VERDICTS[BUDGET_FAIL], exit_code=BUDGET_FAIL)
        run_cost = None
        if (
            mv and prices
        ):  # one run of each version, reused base runs included: continuing pays for both
            per_arm = []
            for arm, side in ((base, 0), (candidate, 1)):
                spent = [record_cost(r, prices) for r in arm.records.values()]
                runs_each = max(len(rs[side]) for rs in full.values())
                per_arm.append(None if None in spent else sum(spent) / runs_each)
            run_cost = None if None in per_arm else sum(per_arm)
        if args.max_spend is not None:
            if None in costs:
                raise ValueError(
                    "a model in these runs has no price: max_spend_usd cannot be kept"
                )
            have = complete(whole[0], cases)
            est_c, est_b = (
                round_cost(whole[1], rounds - 1, prices),
                round_cost(whole[0], have - 1, prices),
            )

            def cost_of(j: int) -> float:
                return est_c + (est_b if j > have else 0.0)

            decided = v.exit_code != INCONCLUSIVE
            nxt = (
                0 if decided else plan(rounds, kc, sum(costs), args.max_spend, cost_of)
            )
            capped = not decided and nxt and rounds + nxt > MAX_ROUNDS
            nxt = 0 if capped or rounds >= MAX_ROUNDS else nxt
            stop = (
                "decided"
                if decided
                else "rounds"
                if rounds >= MAX_ROUNDS or capped
                else None
                if nxt
                else "limit"
            )
            need = (
                None
                if mv.pass_at is None or mv.runs_for_pass is None
                else max(mv.pass_at, mv.runs_for_pass, kc)
            )
            adaptive = {
                "max_spend_usd": args.max_spend, "spent_usd": sum(costs), "k_c": kc, "rounds": rounds,
                "stop": stop, "next_rounds": nxt, "resume": not args.no_resume,
                "next_round_usd": None if decided else cost_of(rounds + 1),
                "rounds_to_k_c": max(0, kc - rounds), "to_k_c_usd": sum(map(cost_of, range(rounds + 1, kc + 1))),
                "pass_rounds": need, "pass_usd": None if need is None else sum(map(cost_of, range(rounds + 1, need + 1))),
                "cases": mv.cases, "silent_rounds": mv.runs_for_pass, "silent_rounds_twice": mv.runs_for_pass_twice,
            }  # fmt: skip
        bound = alpha_line(args.alpha, mv is not None, bool(blocking[0]))
        text = markdown(
            v, base, candidate, costs, spend, checks, mv, lv, run_cost, bound, adaptive
        )
        report = {
            **asdict(v),
            "threshold_pp": args.threshold,
            "relative": args.relative,
            "alpha": {
                "gate": args.alpha,
                "mean": None if mv is None else on_mean,
                "checks": on_checks if blocking[0] else None,
            },
            "mean": None if mv is None else {**asdict(mv), "name": args.mean},
            "checks": checks_report(checks, rules) if checks else None,
            "levels": args.levels,
            "checks_mode": args.checks,
            "checks_reported": checks_report(lv.reported, rules)
            if lv and lv.reported
            else None,
            "warnings": [
                {**asdict(u), "level": rules.of(u.case, u.check)} for u in lv.warnings()
            ]
            if lv
            else [],
            "minor_cases": minor_cases,
            "levels_unmatched": lv.unmatched if lv else [],
            "base_config": base.config_hash,
            "candidate_config": candidate.config_hash,
            "set_hash": base.set_hash,
            "scorer_version": base.scorer_version,
            "rescored": bool(args.golden),
            "cost_usd": dict(zip(("base", "candidate"), costs)) if costs else None,
            "prices_hash": canonical_hash(prices) if prices else None,
            "budget": asdict(spend) if spend else None,
            "models_without_date": sorted(base.aliases | candidate.aliases),
            "base_reused": dict(
                zip(("runs", "days_before_candidate"), reused(base, candidate))
            ),
            # the naive rule reads only the first of these; betting and the rule on checks all
            "runs_per_case": {
                "base": max(len(b) for b, _ in pairs.values()),
                "candidate": max(len(c) for _, c in pairs.values()),
            },
            # the adaptive gate (D-032): this job's spend, why it stopped (None: it buys more), and its rounds
            "spent_usd": adaptive and adaptive["spent_usd"],
            "stop": adaptive and adaptive["stop"],
            "adaptive": adaptive,
        }
        write_all({args.markdown: text, args.json: json.dumps(report, indent=2) + "\n"})
    except (Mismatch, ValueError, OSError) as e:
        print(f"infra error: {e}", file=sys.stderr)
        return INFRA_ERROR
    except Exception:  # noqa: BLE001 - a bug is an infra error too, never a verdict
        traceback.print_exc()
        return INFRA_ERROR
    print(text, end="")
    if (
        lv and os.environ.get("GITHUB_ACTIONS") == "true"
    ):  # an annotation on the job; the exit code stays
        for u in lv.warnings():
            note = (
                f"{lv.rules.of(u.case, u.check).capitalize()} check {u.check} got worse in {u.case}: passed "
                f"{u.base[0]}/{u.base[1]} runs before, {u.candidate[0]}/{u.candidate[1]} now (p {u.adjusted:.2g})."
            )
            print(
                "::warning title=Release gate::"
                + note.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
            )
    return v.exit_code


if __name__ == "__main__":
    sys.exit(main())
