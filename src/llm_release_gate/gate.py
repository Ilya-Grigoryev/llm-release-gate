"""The naive gate: one run per version, block if the mean score drops by more than a fixed threshold."""

import argparse
import json
import math
import sys
import traceback
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from fractions import Fraction
from pathlib import Path

from llm_release_gate.compare import Arm, Mismatch, load_arm, pair
from llm_release_gate.golden import load_cases, validate
from llm_release_gate.metrics import VERSION, score
from llm_release_gate.prices import Prices, load_prices, usd
from llm_release_gate.trace import usage

# Exit codes. 1 and 2 stay with Python and argparse, so a crash is never read as a verdict.
PASS, QUALITY_FAIL, INCONCLUSIVE, BUDGET_FAIL, INFRA_ERROR = 0, 10, 11, 12, 20
VERDICTS = {PASS: "pass", QUALITY_FAIL: "quality fail", INCONCLUSIVE: "inconclusive"}


@dataclass(frozen=True)
class Verdict:
    outcome: str  # pass / quality fail
    exit_code: int
    base_mean: float
    candidate_mean: float
    diff_pp: float  # candidate minus base, percentage points of the mean score
    limit_pp: float  # the drop that blocks, after a relative threshold is applied
    rule: str
    cases: int
    worse: list[tuple[str, float, float]]  # (case, base, candidate), largest drop first


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


def cost(arm: Arm, prices: Prices) -> float | None:
    """USD for the arm's recorded calls; None if a model has no price.

    A record with a trace costs what its model steps cost, the user simulator's included: the price of the decision.
    """
    total = 0.0
    for r in arm.records.values():
        answered = [
            s
            for s in (r.get("trace") or {}).get("steps", [])
            if s["kind"] == "llm" and s.get("status") == "ok"
        ]
        if answered:  # priced by the gate's table, whatever the runner had
            per_actor = usage(r["trace"], prices, reprice=True).values()
            spent = [u["cost_usd"] for u in per_actor]
            if None in spent:
                return None
            total += sum(spent)
            continue
        spent = usd(
            r.get("model"), r.get("input_tokens"), r.get("output_tokens"), prices
        )
        if spent is None:
            return None
        total += spent
    return total


def markdown(
    v: Verdict,
    base: Arm,
    candidate: Arm,
    costs: tuple[float | None, float | None] | None = None,
) -> str:
    icon = {
        "pass": "✅",
        "quality fail": "❌",
        "inconclusive": "⚠️",
        "budget fail": "❌",
    }[v.outcome]
    lines = [
        f"**Release gate: {icon} {v.outcome}**",
        "",
        (
            f"Mean score {v.base_mean:.3f} → {v.candidate_mean:.3f} ({v.diff_pp:+.2f} points, "
            f"blocks below {-v.limit_pp:+.2f}); {v.rule}."
        ),
        (
            f"{v.cases} cases, first run of each version · config {base.config_hash[:8]} → "
            f"{candidate.config_hash[:8]} · set {base.set_hash[:8]}"
        ),
    ]
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
            "(successful calls, list prices)."
        )
    if v.worse:
        lines += ["", "| Case | Base | Candidate |", "|---|---|---|"]
        lines += [f"| {k} | {b:.2f} | {c:.2f} |" for k, b, c in v.worse[:5]]
    return "\n".join(lines) + "\n"


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
    p.add_argument(
        "--base", type=Path, required=True, help="runs of the current version (JSONL)"
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
        "--golden",
        type=Path,
        help="rescore both versions from their saved answers against this set",
    )
    p.add_argument(
        "--prices",
        type=Path,
        help="YAML `model: [input, output]` or `[input, output, cached input]`, USD per 1M tokens",
    )
    p.add_argument("--json", type=Path, help="write the verdict as JSON")
    p.add_argument("--markdown", type=Path, help="write the merge request comment")
    args = p.parse_args(argv)
    try:
        base, candidate = load_arm(args.base), load_arm(args.candidate)
        if args.golden:
            base, candidate = (
                rescored(base, args.golden),
                rescored(candidate, args.golden),
            )
        pairs = pair(base, candidate)
        v = naive(
            {k: first_run(b) for k, (b, _) in pairs.items()},
            {k: first_run(c) for k, (_, c) in pairs.items()},
            args.threshold,
            args.relative,
        )
        prices = load_prices(args.prices) if args.prices else None
        costs = (cost(base, prices), cost(candidate, prices)) if prices else None
        text = markdown(v, base, candidate, costs)
        report = {
            **asdict(v),
            "threshold_pp": args.threshold,
            "relative": args.relative,
            "base_config": base.config_hash,
            "candidate_config": candidate.config_hash,
            "set_hash": base.set_hash,
            "scorer_version": base.scorer_version,
            "rescored": bool(args.golden),
            "cost_usd": dict(zip(("base", "candidate"), costs)) if costs else None,
            "models_without_date": sorted(base.aliases | candidate.aliases),
            # the naive gate uses only the first of these
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
    return v.exit_code


if __name__ == "__main__":
    sys.exit(main())
