"""The naive gate: one run per version, block if the mean score drops by more than a fixed threshold."""

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from llm_release_gate.compare import Arm, Mismatch, load_arm, pair
from llm_release_gate.golden import load_cases, validate
from llm_release_gate.metrics import VERSION, score

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
    worse: list[
        tuple[str, float, float]
    ]  # (case, base, candidate), largest drops first


def naive(
    base: dict[str, float],
    candidate: dict[str, float],
    threshold_pp: float,
    relative: bool = False,
) -> Verdict:
    """Compare the mean of one score per case and arm.

    Absolute: block if the candidate's mean is lower by more than `threshold_pp` points.
    Relative: the limit is `threshold_pp` percent of the base mean.
    """
    if base.keys() != candidate.keys() or not base:
        raise ValueError("the arms must score the same, non-empty set of cases")
    b = sum(base.values()) / len(base)
    c = sum(candidate.values()) / len(candidate)
    diff = 100 * (c - b)
    limit = threshold_pp * b if relative else threshold_pp
    code = QUALITY_FAIL if diff < -limit else PASS
    worse = sorted(
        ((k, base[k], candidate[k]) for k in base if candidate[k] < base[k]),
        key=lambda t: t[2] - t[1],
    )
    rule = f"block if the mean drops by more than {threshold_pp:g} {'% of the base mean' if relative else 'points'}"
    return Verdict(VERDICTS[code], code, b, c, diff, limit, rule, len(base), worse)


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
        result = score(
            cases[r["case"]].expected, r.get("output"), cases[r["case"]].scoring
        )
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
    if r.get("score") is None:
        raise Mismatch(
            f"{r['case']}#{r['rep']}: no score ({r.get('score_error')}); pass --golden to rescore"
        )
    return r["score"]


def markdown(v: Verdict, base: Arm, candidate: Arm) -> str:
    icon = {"pass": "✅", "quality fail": "❌"}[v.outcome]
    lines = [
        f"**Release gate: {icon} {v.outcome}**",
        "",
        f"Mean score {v.base_mean:.3f} → {v.candidate_mean:.3f} ({v.diff_pp:+.1f} points); {v.rule}.",
        f"{v.cases} cases, one run per version · config {base.config_hash[:8]} → {candidate.config_hash[:8]} · set {base.set_hash[:8]}",
    ]
    if v.worse:
        lines += ["", "| Case | Base | Candidate |", "|---|---|---|"]
        lines += [f"| {k} | {b:.2f} | {c:.2f} |" for k, b, c in v.worse[:5]]
    return "\n".join(lines) + "\n"


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
        help="rescore both arms from their saved answers against this set",
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
        text = markdown(v, base, candidate)
        if args.json:
            report = {
                **asdict(v),
                "base_config": base.config_hash,
                "candidate_config": candidate.config_hash,
                "set_hash": base.set_hash,
                "scorer_version": base.scorer_version,
            }
            args.json.write_text(json.dumps(report, indent=2) + "\n")
        if args.markdown:
            args.markdown.write_text(text)
    except Exception as e:  # noqa: BLE001 - a failure to compare is an infra error, never a verdict
        print(f"infra error: {e}", file=sys.stderr)
        return INFRA_ERROR
    print(text, end="")
    return v.exit_code


if __name__ == "__main__":
    sys.exit(main())
