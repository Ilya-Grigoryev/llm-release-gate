"""Run cases against the live API and print what the agent did: `python -m support_agent.run cases/cancel-late.yaml`."""

import argparse
import json
from pathlib import Path

from openai import OpenAI

from support_agent import agent
from support_agent.cases import load_case, reference
from support_agent.world import diff, tool_specs

HERE = Path(__file__).resolve().parents[2]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("cases", nargs="+", type=Path)
    p.add_argument("--model", required=True)
    p.add_argument(
        "--params", type=json.loads, default={}, help='JSON, e.g. {"temperature": 0}'
    )
    p.add_argument(
        "--user-model",
        help="simulate the member with this model; without it the agent works alone",
    )
    p.add_argument("--user-params", type=json.loads, default={})
    p.add_argument("--max-steps", type=int, default=20)
    p.add_argument("--out", type=Path, help="append one JSON line per run")
    a = p.parse_args()
    client = OpenAI()
    policy = (HERE / "policy.md").read_text()
    tools = tool_specs(HERE / "tools.yaml")
    user = a.user_model and {
        "client": client,
        "model": a.user_model,
        "params": a.user_params,
        "guidelines": (HERE / "simulator.md").read_text(),
    }
    for path in a.cases:
        case = load_case(path)
        world = case.world()
        before = world.state()
        t = agent.run(
            case,
            world,
            client=client,
            model=a.model,
            params=a.params,
            policy=policy,
            tools=tools,
            user=user or None,
            max_steps=a.max_steps,
        )
        got, (_, want) = diff(before, world.state()), reference(case)
        print(
            f"\n== {case.id} ({'chat' if user else 'solo'}): stop={t.stop}, tokens={t.tokens}"
        )
        for e in t.events:
            print("  ", json.dumps(e, ensure_ascii=False)[:300])
        print(
            f"   changed: {got}\n   expected: {want}\n   state matches: {got == want}"
        )
        if a.out:
            with a.out.open("a") as f:
                row = {
                    "case": case.id,
                    "mode": "chat" if user else "solo",
                    "model": a.model,
                    "params": a.params,
                    "user_model": a.user_model,
                    "stop": t.stop,
                    "tokens": t.tokens,
                    "reported": t.model,
                    "events": t.events,
                    "changed": got,
                    "expected": want,
                }
                f.write(json.dumps(row, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
