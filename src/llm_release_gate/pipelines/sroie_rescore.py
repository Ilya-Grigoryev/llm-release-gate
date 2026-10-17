"""Rescore recorded SROIE runs from their saved answers, without calling the model.

Local only: the expected values come from the SROIE split in data/, which CI does not have.
"""

import argparse
from pathlib import Path

from llm_release_gate.metrics import score
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
        help="typed: SCORING (D-005); text: whitespace and case only; strict: exact, as the ICDAR evaluation",
    )
    args = p.parse_args()
    scoring = VARIANTS[args.variant]
    by_id = {c.id: c for c in cases(args.data)}
    scores, changed = [], 0
    for path in args.runs:
        file_scores = []
        for r in read_records(path):
            if r["case"] not in by_id:
                raise SystemExit(f"{path}: case {r['case']} is not in {args.data}")
            case = by_id[r["case"]]
            result = score(case.expected, r.get("output"), scoring)
            file_scores.append(result["score"])
            changed += "hits" in r and r["hits"] != result["per_field"]
        print(f"{path.name}: {len(file_scores)} records, mean {average(file_scores)}")
        scores += file_scores
    print(f"all: {len(scores)} records, mean {average(scores)}")
    print(f"records whose saved hits differ from the rescore: {changed}")


def average(values: list[float | None]) -> str:
    scored = [v for v in values if v is not None]
    return f"{sum(scored) / len(scored):.3f}" if scored else "-"


if __name__ == "__main__":
    main()
