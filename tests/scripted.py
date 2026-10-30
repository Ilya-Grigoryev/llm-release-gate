"""A scripted agent program for the runner's tests: it adds 5 to a balance with one tool call, as a program would report
it. `program` runs it through the gate's `Command`."""

import json
import sys
from pathlib import Path

from llm_release_gate.command import Command
from llm_release_gate.pipeline import load_config

FIXTURES = Path(__file__).parent / "fixtures"
SCRIPTED = FIXTURES / "command" / "scripted.py"


def llm(text=None, calls=(), tokens=(100, 10), actor="agent"):
    step = {
        "kind": "llm",
        "actor": actor,
        "status": "ok",
        "model": "fake-model-2026-01-01",
        "tokens_in": tokens[0],
        "tokens_out": tokens[1],
        "cost_usd": None,
    }
    if calls:
        step["tool_calls"] = [{"id": i, "name": n, "args": a} for i, n, a in calls]
    if text:
        step["text"] = text
    return step


def failed(attempt=1):
    return {
        "kind": "llm",
        "actor": "agent",
        "status": "error",
        "error": "Timeout",
        "attempt": attempt,
    }


def tool(call_id="c1", result=None):
    return {
        "kind": "tool",
        "actor": "agent",
        "call_id": call_id,
        "name": "add",
        "args": {"amount": 5},
        "status": "ok",
        "result": result if result is not None else {"balance": 5},
    }


ADDED = [
    llm(calls=[("c1", "add", {"amount": 5})]),
    tool(),
    llm("Added 5.", tokens=(130, 5)),
]


def answer(steps=ADDED, **trace):
    """A program's answer after adding 5; `trace` adds end-state fields."""
    end = {
        "final_state": {"balance": 5},
        "state_change": {"balance": 5},
        "stop": "done",
    }
    return {
        "output": {"balance": 5},
        "raw": "Added 5.",
        "model": "fake-model-2026-01-01",
        "trace": {"steps": steps, **end, **trace},
    }


def config(tmp_path: Path, script: dict) -> Path:
    """A version whose program plays `script`: case id → attempts, each {"answer": ..., "exit": ...}."""
    (tmp_path / "script.json").write_text(json.dumps(script))
    path = tmp_path / "program.yaml"
    path.write_text(
        f"command: {json.dumps([sys.executable, str(SCRIPTED)])}\n"
        f"model: fake-model-2026-01-01\nprompt: {FIXTURES / 'prompt.md'}\ninput: text\n"
        f"params: {{script: {tmp_path / 'script.json'}}}\n"
    )
    return path


def program(tmp_path: Path, script: dict) -> Command:
    return Command(load_config(config(tmp_path, script)))
