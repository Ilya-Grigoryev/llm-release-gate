"""Operational state of the drift jobs, blind to results: per job its event, whether a pair hit an infrastructure error,
and per side runs, errors, retries and cost; then the cost so far and the forecast for the whole series. Never prints
scores, checks, verdicts or exit codes. Reads what fetch-drift.sh copied; prices come from each application's
prices.yaml.  uv run python study/drift-status.py [DEST] [APPS]"""

import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

from llm_release_gate.prices import load_prices, usd
from llm_release_gate.trace import usage

INFRA = 20
# scheduled jobs of the series (study/drift-job.md): (repository, has a change pair) -> count from 25.11. to 05.01.
PLANNED = {
    ("workbench-support", False): 42,
    ("workbench-support", True): 42,
    ("receipt-intake", False): 42,
    ("receipt-intake", True): 42,
    ("telecom-support", False): 12,
}
END = date(2027, 1, 5)


def run_cost(r: dict, prices) -> float:
    """USD of one run: its model steps if it has a trace, else its own token counts (as the gate prices them)."""
    if (r.get("trace") or {}).get("steps"):
        return sum(
            u["cost_usd"] or 0 for u in usage(r["trace"], prices, reprice=True).values()
        )
    return (
        usd(r.get("model"), r.get("input_tokens"), r.get("output_tokens"), prices) or 0
    )


dest = Path(sys.argv[1] if len(sys.argv) > 1 else "data/runs/drift")
apps = Path(sys.argv[2] if len(sys.argv) > 2 else "../apps")
spent, per_kind = 0.0, defaultdict(list)
for run in sorted(p for p in dest.glob("*/*") if p.is_dir()):
    repo = run.parent.name
    prices = load_prices(apps / repo / "prices.yaml")
    info = (
        json.loads((run / "run.json").read_text())
        if (run / "run.json").is_file()
        else {}
    )
    meta = next(run.glob("*/meta.json"), None)
    pairs = json.loads(meta.read_text()).get("pairs", []) if meta else []
    infra = [p["pair"] for p in pairs if p["exit"] == INFRA]
    event = info.get("event", "?")
    print(
        f"{repo} {run.name} {event} {info.get('created_at', '?')} pairs {[p['pair'] for p in pairs]} "
        f"infra {infra or 'none'}"
    )
    job_cost = 0.0
    for side in sorted(run.glob("*/*/*/*.jsonl")):
        if side.stem not in ("base", "candidate"):
            continue
        rs = [
            json.loads(line) for line in side.read_text().splitlines() if line.strip()
        ]
        cost = sum(run_cost(r, prices) for r in rs)
        job_cost += cost
        jobs = {r.get("ci_job") for r in rs}
        print(
            f"  {side.parent.parent.name}/{side.stem}: {len(rs)} runs, {sum(bool(r.get('error')) for r in rs)} errors, "
            f"{sum(r.get('retries') or 0 for r in rs)} retries, ${cost:.3f}, ci_job {jobs}"
        )
    spent += job_cost
    if event == "schedule":
        per_kind[(repo, any(p["pair"] == "change" for p in pairs))].append(job_cost)
done = {k: len(v) for k, v in per_kind.items()}
left = sum(max(0, n - done.get(k, 0)) for k, n in PLANNED.items())
forecast = spent + sum(
    max(0, n - done.get(k, 0)) * (sum(per_kind[k]) / len(per_kind[k]))
    for k, n in PLANNED.items()
    if per_kind.get(k)
)
unknown = [k for k in PLANNED if not per_kind.get(k)]
print(
    f"\nspent ${spent:.2f} (smoke tests included); {left} scheduled jobs left until {END}; "
    f"forecast ${forecast:.2f}"
    + (f" plus kinds not seen yet: {unknown}" if unknown else "")
)
