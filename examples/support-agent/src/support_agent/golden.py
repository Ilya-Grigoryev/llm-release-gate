"""Build the gate's golden set from `cases/`: `python -m support_agent.golden --mode solo --out golden/solo`.

A golden case points to the case file and the shared world (and, in a chat set, to the member simulator, so the
simulator is part of the set's hash). The expected change comes from running the case's reference actions; the
checks ask for that change and for the agent's own conduct, and the case passes only if every check does.
"""

import argparse
import shutil
from pathlib import Path

import yaml

from support_agent.cases import load_cases, reference

HERE = Path(__file__).resolve().parents[2]
WRITES = ["create_booking", "cancel_booking", "issue_credit", "escalate_to_human"]
CHECKS = [
    {"id": "state", "kind": "state", "key": "state_change"},
    {"id": "acted", "kind": "active"},
    {"id": "verified", "kind": "order", "first": "find_member", "then": WRITES},
    {
        "id": "credit-limit",
        "kind": "not_called",
        "tool": "issue_credit",
        "args": {"amount_eur": {"gt": 30}},
    },
    {"id": "steps", "kind": "max_steps", "max": 15},
]


def build(cases_dir: Path, out: Path, mode: str) -> list[str]:
    """Write the golden set for `mode` (solo or chat) into an empty `out`; return the case ids."""
    if out.exists() and any(out.iterdir()):
        raise ValueError(f"{out} is not empty")
    inputs = out / "inputs"
    inputs.mkdir(parents=True)
    shutil.copy(cases_dir / "world.yaml", inputs / "world.yaml")
    if mode == "chat":
        shutil.copy(cases_dir / "simulator.yaml", inputs / "simulator.yaml")
    ids = []
    for case in load_cases(cases_dir):
        shutil.copy(cases_dir / f"{case.id}.yaml", inputs / f"{case.id}.yaml")
        _, change = reference(case)
        golden = {
            "id": case.id,
            "version": 1,
            "slices": {"category": case.category},
            "source": f"examples/support-agent/cases/{case.id}.yaml",
            "input": {
                "case": f"inputs/{case.id}.yaml",
                "world": "inputs/world.yaml",
                **({"simulator": "inputs/simulator.yaml"} if mode == "chat" else {}),
            },
            "expected": {
                "state_change": change,
                "actions": [
                    {"tool": t, "args": a} for t, a in case.actions if t in WRITES
                ],
            },
            "scoring": {"method": "checks", "aggregate": "all", "checks": CHECKS},
        }
        (out / f"{case.id}.yaml").write_text(yaml.safe_dump(golden, sort_keys=False))
        ids.append(case.id)
    return ids


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=["solo", "chat"], required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--cases", type=Path, default=HERE / "cases")
    a = p.parse_args()
    ids = build(a.cases, a.out, a.mode)
    print(f"{len(ids)} cases written to {a.out}")


if __name__ == "__main__":
    main()
