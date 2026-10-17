"""Rescore recorded SROIE runs from their saved answers, without calling the model.

Local only: the expected values come from the SROIE split in data/, which CI does not have.
"""

import argparse
import json
from pathlib import Path

from llm_release_gate.metrics import VERSION, score
from llm_release_gate.pipelines.sroie import SCORING, cases
from llm_release_gate.runner import read_records

VARIANTS = {
    "typed": SCORING,
    "text": {"method": "field_match", "normalise": ["whitespace", "casefold"]},
    "strict": {"method": "field_match"},
}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "runs", type=Path, nargs="+", help="JSONL files with case and output"
    )
    p.add_argument(
        "--data", type=Path, default=Path("data/SROIE2019/train"), help="SROIE split"
    )
    p.add_argument(
        "--variant",
        choices=sorted(VARIANTS),
        default="typed",
        help="typed: SCORING (D-005); text: whitespace and case, as before 17 Oct; strict: exact strings, the ICDAR comparison rule",
    )
    p.add_argument(
        "--write",
        type=Path,
        help="also write a copy of each file into this directory, with hits and score from the rescore",
    )
    args = p.parse_args()
    scoring = VARIANTS[args.variant]
    if args.write:
        args.write.mkdir(parents=True, exist_ok=True)
    # Only the gate's scorer leaves an empty label unscored; text and strict count it, like E-002 and ICDAR.
    by_id = {c.id: c for c in cases(args.data, empty_as_null=args.variant == "typed")}
    scores, changed = [], 0
    for path in args.runs:
        file_scores, copies = [], []
        for r in read_records(path):
            if r["case"] not in by_id:
                raise SystemExit(f"{path}: case {r['case']} is not in {args.data}")
            case = by_id[r["case"]]
            result = score(case.expected, r.get("output"), scoring)
            file_scores.append(result["score"])
            changed += "hits" in r and r["hits"] != result["per_field"]
            rescored = {"variant": args.variant, "scorer_version": f"metrics/{VERSION}"}
            hits = {"hits": result["per_field"], "score": result["score"]}
            # only the gate's own scorer may look like a gate record to compare
            version = f"metrics/{VERSION}" + (
                "" if args.variant == "typed" else f"+{args.variant}"
            )
            copies.append(
                {**r, **hits, "scorer_version": version, "rescored": rescored}
            )
        if args.write:
            if (args.write / path.name).resolve() == path.resolve():
                raise SystemExit(f"{path}: --write must not overwrite the source")
            text = "".join(json.dumps(c) + "\n" for c in copies)
            (args.write / path.name).write_text(text)
        print(f"{path.name}: {len(file_scores)} records, mean {average(file_scores)}")
        scores += file_scores
    print(f"all: {len(scores)} records, mean {average(scores)}")
    print(f"records whose saved hits differ from the rescore: {changed}")


def average(values: list[float | None]) -> str:
    scored = [v for v in values if v is not None]
    return f"{sum(scored) / len(scored):.3f}" if scored else "-"


if __name__ == "__main__":
    main()
