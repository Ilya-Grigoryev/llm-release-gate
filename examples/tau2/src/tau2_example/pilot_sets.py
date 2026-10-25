"""The golden sets of experiment E-005 (model pilot): `python -m tau2_example.pilot_sets OUT`.

Ten `small` tasks: the six where tau2 expects the agent itself to act, and four of the other fourteen by seed 0. One solo
set for both models; one chat set per model, since the model plays the user too and the simulator is part of the set.
"""

import argparse
import random
from pathlib import Path

from tau2.runner import load_task_splits, load_tasks

from tau2_example import golden

MODELS = {
    "a": {"model": "gpt-5.4-mini-2026-03-17", "params": {"temperature": 0}},
    "b": {
        "model": "gpt-6-luna",
        "params": {"temperature": 0, "extra_body": {"reasoning_effort": "none"}},
    },
}


def tasks() -> list[str]:
    small = sorted(load_task_splits("telecom")["small"])
    by_id = {t.id: t for t in load_tasks("telecom")}
    acts = [
        i
        for i in small
        if any(
            a.requestor == "assistant"
            for a in by_id[i].evaluation_criteria.actions or []
        )
    ]
    rest = [i for i in small if i not in acts]
    return acts + sorted(random.Random(0).sample(rest, 4))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("out", type=Path)
    out = p.parse_args().out
    ids, splits = tasks(), load_task_splits("telecom")
    print("solo", golden.build(ids, splits, out / "solo", "solo", MODELS["a"]))
    for key, user in MODELS.items():
        print(
            f"chat-{key}", golden.build(ids, splits, out / f"chat-{key}", "chat", user)
        )


if __name__ == "__main__":
    main()
