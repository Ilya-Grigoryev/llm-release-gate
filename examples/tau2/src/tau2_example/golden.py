"""Build the gate's golden set from tau2's telecom tasks: `python -m tau2_example.golden --mode solo`.

A manifest (`golden/telecom-<mode>.yaml`, in git) is the source of truth: the set is rebuilt from its tau2 task ids
(`tasks`; `ids` are the case ids that `golden validate --manifest` compares). Without
one, the generator takes the `small` split and `--train` tasks sampled from `train` with `--seed` (the `test` split stays
held out), and writes the manifest. Each case points to its tau2 task and to `run.yaml`: tau2's version, the run limits
and, in a chat set, the user simulator (model, parameters, the hash of its guidelines), so the simulator is part of the
set's hash. The checks: tau2's reward, each of its environment assertions, the expected actions the agent must take
(all of them alone, the `assistant` ones in a chat) and that the agent called a tool at all.
"""

import argparse
import hashlib
import importlib.metadata
import random
import re
from pathlib import Path

import yaml
from tau2.runner import load_task_splits, load_tasks

from llm_release_gate.golden import validate
from tau2_example.gate_adapter import GLOBAL_USER_SIM_GUIDELINES_PATH_TOOLS

HERE = Path(__file__).resolve().parents[2]
SEED = 300  # tau2's default run seed
USER = {"model": "gpt-5.4-mini-2026-03-17", "params": {"temperature": 0}}


def case_id(task_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", task_id).strip("-")


def checks(task, solo: bool) -> list[dict]:
    criteria = task.evaluation_criteria
    out = [{"id": "reward", "kind": "number", "field": "reward", "value": 1}]
    for i, a in enumerate(criteria.env_assertions or []):
        out.append(
            {
                "id": f"assert-{i}",
                "kind": "number",
                "field": f"assertions.{i}-{a.func_name}",
                "value": 1,
            }
        )
    for j, a in enumerate(criteria.actions or []):
        if solo or a.requestor == "assistant":
            keys = a.arguments if a.compare_args is None else a.compare_args
            args = {k: a.arguments[k] for k in keys if k in a.arguments}
            out.append(
                {
                    "id": f"action-{j}-{a.name}",
                    "kind": "called",
                    "tool": a.name,
                    "args": args,
                }
            )
    out.append({"id": "agent-acted", "kind": "active"})
    return out


def build(
    ids: list[str], splits: dict[str, list[str]], out: Path, mode: str, user: dict
) -> str:
    """Write the set for `mode` into an empty `out`; return its hash."""
    if out.exists() and any(out.iterdir()):
        raise ValueError(f"{out} is not empty")
    tasks = {t.id: t for t in load_tasks("telecom")}
    missing = sorted(set(ids) - tasks.keys())
    if missing:
        raise ValueError(f"tasks not in tau2's telecom: {missing}")
    inputs = out / "inputs"
    inputs.mkdir(parents=True)
    run = {"tau2": importlib.metadata.version("tau2"), "domain": "telecom", "seed": SEED, "max_steps": 100,
           "max_errors": 10}  # fmt: skip
    if mode == "chat":
        guidelines = hashlib.sha256(
            GLOBAL_USER_SIM_GUIDELINES_PATH_TOOLS.read_bytes()
        ).hexdigest()
        run["user"] = {**user, "guidelines_sha256": guidelines}
    (inputs / "run.yaml").write_text(yaml.safe_dump(run, sort_keys=False))
    for task_id in ids:
        task, cid = tasks[task_id], case_id(task_id)
        (inputs / f"{cid}.json").write_text(task.model_dump_json(indent=1))
        split = next(s for s in ("small", "train", "test") if task_id in splits[s])
        golden = {
            "id": cid,
            "version": 1,
            "slices": {"split": split, "category": task_id.split("]")[0].lstrip("[")},
            "source": f"tau2-bench v{run['tau2']} telecom: {task_id}",
            "input": {"task": f"inputs/{cid}.json", "run": "inputs/run.yaml"},
            "expected": {"reward": 1},
            "scoring": {
                "method": "checks",
                "aggregate": "all",
                "checks": checks(task, mode == "solo"),
            },
        }
        (out / f"{cid}.yaml").write_text(
            yaml.safe_dump(golden, sort_keys=False, allow_unicode=True)
        )
    set_hash, errors = validate(out)
    if errors:
        raise ValueError(f"{out}: {errors}")
    return set_hash


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=["solo", "chat"], required=True)
    p.add_argument(
        "--out", type=Path, help="default: ../../data/golden/tau2-telecom-<mode>"
    )
    p.add_argument("--manifest", type=Path, help="default: golden/telecom-<mode>.yaml")
    p.add_argument(
        "--train",
        type=int,
        default=10,
        help="tasks sampled from `train` besides `small` (new manifest)",
    )
    p.add_argument("--seed", type=int, default=0)
    p.add_argument(
        "--rehash",
        action="store_true",
        help="same tasks, new set hash: record it in the manifest",
    )
    a = p.parse_args()
    out = a.out or HERE.parents[1] / "data" / "golden" / f"tau2-telecom-{a.mode}"
    manifest_path = a.manifest or HERE / "golden" / f"telecom-{a.mode}.yaml"
    splits = load_task_splits("telecom")
    manifest = (
        yaml.safe_load(manifest_path.read_text()) if manifest_path.exists() else None
    )
    if manifest:
        ids = manifest["tasks"]
        user = manifest.get("user", USER)
    else:
        ids = sorted(splits["small"]) + sorted(
            random.Random(a.seed).sample(sorted(splits["train"]), a.train)
        )
        user = USER
    set_hash = build(ids, splits, out, a.mode, user)
    if manifest and set_hash != manifest["sha256"] and not a.rehash:
        raise SystemExit(
            f"rebuilt set hash {set_hash} differs from {manifest_path}; --rehash records it"
        )
    if not manifest:
        manifest = {"source": "tau2-bench v1.0.1 telecom", "mode": a.mode, "small": len(splits["small"]),
                    "train": a.train, "seed": a.seed, **({"user": user} if a.mode == "chat" else {}), "tasks": ids,
                    "ids": sorted(case_id(i) for i in ids)}  # fmt: skip
    manifest["sha256"] = set_hash
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True)
    )
    print(f"{len(ids)} cases in {out}, sha256 {set_hash}, manifest {manifest_path}")


if __name__ == "__main__":
    main()
