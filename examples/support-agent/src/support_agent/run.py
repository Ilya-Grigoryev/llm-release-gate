"""Run cases against the live API and print what the agent did: `python -m support_agent.run cases/cancel-late.yaml`."""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import yaml
from openai import OpenAI

from support_agent import agent
from support_agent.cases import load_case, reference
from support_agent.world import diff, tool_specs

HERE = Path(__file__).resolve().parents[2]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("cases", nargs="+", type=Path)
    p.add_argument("--model", required=True)
    p.add_argument(
        "--params", type=json.loads, default={}, help='JSON, e.g. {"temperature": 0}'
    )
    p.add_argument(
        "--chat",
        action="store_true",
        help="a simulated member chats, as set in cases/simulator.yaml",
    )
    p.add_argument("--max-steps", type=int, default=20)
    p.add_argument("--max-turns", type=int, default=10)
    p.add_argument("--out", type=Path, help="append one JSON line per run")
    a = p.parse_args()
    client = OpenAI()
    policy = (HERE / "policy.md").read_text()
    tools = tool_specs(HERE / "tools.yaml")
    version = {"policy": sha(HERE / "policy.md"), "tools": sha(HERE / "tools.yaml")}
    for path in a.cases:
        case = load_case(path)
        sim_file = path.parent / "simulator.yaml"
        user = None
        if a.chat:
            user = {"client": client, **yaml.safe_load(sim_file.read_text())}
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
            user=user,
            max_steps=a.max_steps,
            max_turns=a.max_turns,
        )
        got, (_, want) = diff(before, world.state()), reference(case)
        mode = "chat" if user else "solo"
        print(f"\n== {case.id} ({mode}): stop={t.stop}, tokens={t.tokens}")
        for e in t.events:
            print("  ", json.dumps(e, ensure_ascii=False)[:300])
        print(
            f"   changed: {got}\n   expected: {want}\n   state matches: {got == want}"
        )
        if a.out:
            row = {
                "case": case.id,
                "mode": mode,
                "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
                "model": a.model,
                "params": a.params,
                "max_steps": a.max_steps,
                "version": version,
                "simulator": user
                and {
                    "model": user["model"],
                    "params": user["params"],
                    "sha": sha(sim_file),
                },
                "stop": t.stop,
                "tokens": t.tokens,
                "reported": t.model,
                "events": t.events,
                "changed": got,
                "expected": want,
            }
            with a.out.open("a") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
