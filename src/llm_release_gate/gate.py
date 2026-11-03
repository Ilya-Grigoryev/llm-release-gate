"""The gate: a rule on the mean (naive: first run per version, a fixed threshold; or betting over all runs) and the rule
on checks (all runs)."""

import argparse
import json
import math
import os
import sys
import traceback
from collections.abc import Sequence
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
    pairs: dict[str, tuple[list[dict], list[dict]]], delta_pp: float, method: str
) -> tuple[Verdict, mean.MeanVerdict]:
    """The rule on the mean over all runs (D-004 C, D-026 C): pass, block (quality fail) or inconclusive."""
    base = {k: all_runs(b) for k, (b, _) in pairs.items()}
    candidate = {k: all_runs(c) for k, (_, c) in pairs.items()}
    mv = mean.decide(base, candidate, delta_pp / 100, **mean.METHODS[method])
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


def mean_lines(mv: mean.MeanVerdict, cost_per_run: float | None) -> list[str]:
    """What the betting rule showed, and what a pass would take."""
    span = f"[{100 * mv.lower:+.1f}, {100 * mv.upper:+.1f}] points (95 %)"
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
    if need is None:
        return [
            f"{shown}; not decided. With this method and {mv.cases} case{'s' if mv.cases != 1 else ''} a pass needs more than 10 000 runs."
        ]
    more = max(0, need - mv.runs)
    floor = (
        f"A pass needs at least {need} runs of each version even if nothing changed "
        f"({mv.cases} case{'s' if mv.cases != 1 else ''}, δ {100 * mv.delta:g} points, α {mv.alpha:g})"
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
    """Per (case, check), its result in every run of the base and of the candidate; a run without results gives None."""
    keys = sorted(
        {(case, check) for case, arms in pairs.items() for rs in arms for r in rs for check in r.get("hits") or {}}
    )  # fmt: skip
    base, candidate = (
        {(case, check): [(r.get("hits") or {}).get(check) for r in pairs[case][side]] for case, check in keys}
        for side in (0, 1)
    )  # fmt: skip
    return base, candidate


def run_counts(c: criterion.CheckVerdict) -> tuple[int, int]:
    """The most runs any check had in the base and in the candidate."""
    return max(u.base[1] for u in c.units), max(u.candidate[1] for u in c.units)


def level(c: criterion.CheckVerdict) -> Fraction:
    """The threshold Tarone's m leaves for each check."""
    return Fraction(str(c.alpha)) / c.m


def blockable(c: criterion.CheckVerdict) -> bool:
    """Whether a check broken in every run could block, at its own run counts and the threshold Tarone's m leaves."""
    counts = {(u.base[1], u.candidate[1]) for u in c.units}
    return any(criterion.can_block(b, k, level(c), c.sides) for b, k in counts)


def checks_report(
    c: criterion.CheckVerdict, rules: levels.Levels | None = None
) -> dict:
    rules = rules or levels.Levels()
    return {
        "outcome": c.outcome,
        "mode": c.mode,
        "alpha": c.alpha,
        "sides": c.sides,
        "m": c.m,
        "testable": c.testable,
        "can_block": bool(c.units) and blockable(c),
        "runs_to_block": criterion.runs_to_block(level(c), c.sides),
        "checked": len(c.units),
        "one_sided": [list(k) for k in c.one_sided],
        "broken": [{**asdict(u), "level": rules.of(u.case, u.check)} for u in c.broken],
    }


def checks_lines(
    c: criterion.CheckVerdict, label: str = "Checks"
) -> tuple[str, list[str]]:
    """The comment's line on the rule on checks, and its table of broken checks."""
    left = (
        f" {len(c.one_sided)} checks scored in one version only are left out."
        if c.one_sided
        else ""
    )
    if not c.units:
        return f"{label}: no check was scored in both versions.{left}", []
    kb, kc = run_counts(c)
    name = f"{'one' if c.sides == 1 else 'two'}-sided Fisher, α {c.alpha:g}"
    test = f"{name}, on {kb} + {kc} runs"
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
            f"| {u.case} | {u.check} | {u.base[0]}/{u.base[1]} | {u.candidate[0]}/{u.candidate[1]} | {u.p:.2g} |"
            for u in c.broken[:5]
        ]
        if len(c.broken) > 5:
            rows += ["", f"{len(c.broken) - 5} more in the JSON report."]
        return (
            f"{label}: {len(c.broken)} broke, {verb} ({test}, Tarone m = {c.m}).{left}",
            rows,
        )
    worse = sum(
        u.candidate[0] * u.base[1] < u.base[0] * u.candidate[1] for u in c.units
    )
    fewer = f" {worse} of {len(c.units)} passed less often." if worse else ""
    if not blockable(c):
        need = criterion.runs_to_block(level(c), c.sides)
        which = (
            "a single broken check"
            if c.m == 1
            else f"Tarone counts {c.m} checks that changed or vary, and a break among them"
        )
        line = (
            f"{label}: with {kb} + {kc} runs no break can be significant; {which} can block from {need} runs of each "
            f"version ({name}).{fewer}{left}"
        )
        return line, []
    if worse:
        line = (
            f"{label}: none significantly worse; {worse} of {len(c.units)} passed less often ({test}, Tarone m = {c.m})."
            f"{left}"
        )
        return line, []
    return f"{label}: none broke ({len(c.units)} checked, {test}).{left}", []


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
        *(mean_lines(mv, run_cost) if mv else []),
        (
            f"{v.cases} cases, {'first run' if mv is None else f'{v.runs} run{"s" if v.runs != 1 else ""}'} of each version · config "
            f"{base.config_hash[:8]} → {candidate.config_hash[:8]} · set {base.set_hash[:8]}"
        ),
    ]
    line, broken = checks_lines(checks) if checks else (None, [])
    if line:
        lines.append(line)
    if lv and lv.reported:
        line, more = checks_lines(
            lv.reported,
            "Checks that only report (minor; normal under `checks: report`)",
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
            f"⚠️ Model without a date ({', '.join(aliases)}): the provider may change it; "
            "the runs of both versions have no pause longer than an hour, and where both asked for the same model the provider "
            "reported the same one."
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
    p.add_argument("--json", type=Path, help="write the verdict as JSON")
    p.add_argument("--markdown", type=Path, help="write the merge request comment")
    args = p.parse_args(argv)
    try:
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
        full = pair(base, candidate)
        rules = levels.Levels.parse(args.levels)
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
            )
        runs = check_runs(full)  # minor cases too: their checks warn
        lv = None
        if rules:
            (blocking, reporting) = families(runs, rules, args.checks)
            checks = (
                criterion.per_check(*blocking, mode="block") if blocking[0] else None
            )
            reported = (
                criterion.per_check(*reporting, mode="report") if reporting[0] else None
            )
            lv = Levelled(rules, reported, minor_cases, rules.unmatched(runs[0]))
        else:
            checks = criterion.per_check(*runs, mode=args.checks) if runs[0] else None
        if v.exit_code != QUALITY_FAIL and checks and checks.outcome == "block":
            v = replace(v, outcome=VERDICTS[QUALITY_FAIL], exit_code=QUALITY_FAIL)
        prices = load_prices(args.prices) if args.prices else None
        costs = (cost(base, prices), cost(candidate, prices)) if prices else None
        spend = candidate_budget(candidate, prices, args)
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
        text = markdown(v, base, candidate, costs, spend, checks, mv, lv, run_cost)
        report = {
            **asdict(v),
            "threshold_pp": args.threshold,
            "relative": args.relative,
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
                f"{u.base[0]}/{u.base[1]} runs before, {u.candidate[0]}/{u.candidate[1]} now (p {u.p:.2g})."
            )
            print(
                "::warning title=Release gate::"
                + note.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
            )
    return v.exit_code


if __name__ == "__main__":
    sys.exit(main())
