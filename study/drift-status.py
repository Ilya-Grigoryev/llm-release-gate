"""Operational state of the drift jobs, without scores: per job its event, pairs, exit codes and, per side, runs,
errors, retries, tokens and the CI job. Reads what fetch-drift.sh copied:  python study/drift-status.py [DEST]"""

import json
import sys
from pathlib import Path

dest = Path(sys.argv[1] if len(sys.argv) > 1 else "data/runs/drift")
for run in sorted(p for p in dest.glob("*/*") if p.is_dir()):
    meta = next(run.glob("*/meta.json"), None)
    info = (
        json.loads((run / "run.json").read_text())
        if (run / "run.json").is_file()
        else {}
    )
    m = json.loads(meta.read_text()) if meta else {}
    pairs = {p["pair"]: p["exit"] for p in m.get("pairs", [])}
    print(
        f"{run.parent.name} {run.name} {info.get('event', '?')} {info.get('created_at', '?')} exits {pairs}"
    )
    for side in sorted(run.glob("*/*/*/*.jsonl")):
        if side.name.endswith(".native.jsonl") or side.stem not in (
            "base",
            "candidate",
        ):
            continue
        rs = [
            json.loads(line) for line in side.read_text().splitlines() if line.strip()
        ]
        jobs = {r.get("ci_job") for r in rs}
        tokens = sum(
            (r.get("input_tokens") or 0) + (r.get("output_tokens") or 0) for r in rs
        )
        print(
            f"  {side.parent.parent.name}/{side.stem}: {len(rs)} runs, {sum(bool(r.get('error')) for r in rs)} errors, "
            f"{sum(r.get('retries') or 0 for r in rs)} retries, {tokens} tokens, ci_job {jobs}"
        )
