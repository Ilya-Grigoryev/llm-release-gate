"""What happened inside one run of a case, step by step (format: D-019).

The runner keeps one `Trace` per (case, repetition) and makes it current while the program runs; `command.record` fills
it from the trace in the program's answer, also after a failed exit, so a run that fails halfway keeps the steps it paid
for.
"""

import contextlib
import contextvars
import json
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from llm_release_gate import protocol
from llm_release_gate.prices import Prices, usd

VERSION = 1
ACTORS = tuple(protocol.SCHEMA["$defs"]["step"]["properties"]["actor"]["enum"])
_current: contextvars.ContextVar["Trace | None"] = contextvars.ContextVar(
    "trace", default=None
)


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def current() -> "Trace | None":
    """The trace of the run in progress on this thread, or None outside the runner."""
    return _current.get()


@contextlib.contextmanager
def active(trace: "Trace | None") -> Iterator["Trace | None"]:
    token = _current.set(trace)
    try:
        yield trace
    finally:
        _current.reset(token)


def problems(step: dict) -> list[str]:
    """What makes a step break the format (`protocol.schema.json`, `step`)."""
    return protocol.errors(step, "step")


def plain(value: Any) -> Any:
    """`value` as JSON can hold it: what does not serialize becomes its repr."""
    return json.loads(json.dumps(value, default=repr))


class Trace:
    def __init__(self):
        self.steps: list[dict] = []
        self.final_state: Any = None
        self.state_change: Any = None
        self.stop: str | None = None
        self.run_attempt = (
            0  # the runner's attempt; a retried run keeps the steps it paid for
        )
        self.native: list = []  # raw provider responses, written next to the record; nothing records them yet
        self.notes: list[str] = []  # what went unrecorded, and why
        self.wall_s: float | None = None
        self.lock = threading.RLock()

    def step(self, kind: str, actor: str, /, **fields: Any) -> dict:
        """Add a step (the manual path). Raises ValueError if it breaks the format."""
        with self.lock:
            step = {"ts": now(), **fields}
            step.update(
                seq=len(self.steps),
                kind=kind,
                actor=actor,
                run_attempt=self.run_attempt,
            )
            found = problems(step)
            if found:
                raise ValueError(f"bad {kind} step: {'; '.join(found)}")
            step = plain(
                step
            )  # what JSON cannot hold becomes its repr, so the record always writes
            self.steps.append(step)
            return step

    def empty(self) -> bool:
        return (
            not (self.steps or self.notes or self.stop)
            and self.final_state is None
            and self.state_change is None
        )

    def to_dict(self) -> dict:
        out = {
            "v": VERSION,
            "steps": self.steps,
            "final_state": plain(self.final_state),
            "state_change": plain(self.state_change),
            "stop": self.stop,
            "last_attempt": self.run_attempt,
        }
        if self.notes:
            out["notes"] = self.notes
        return out


def usage(
    trace: dict, prices: Prices | None = None, reprice: bool = False
) -> dict[str, dict]:
    """Calls, tokens and USD per actor over every answered model call, abandoned attempts too: all were paid for.

    A step without a price is priced from `prices`, and with `reprice` every step is; `cost_usd` is None if some call
    stays unpriced.
    """
    out: dict[str, dict] = {}
    for s in trace["steps"]:
        if s["kind"] != "llm" or s.get("status") != "ok":
            continue
        u = out.setdefault(
            s["actor"],
            {"llm_calls": 0, "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0},
        )
        u["llm_calls"] += 1
        u["tokens_in"] += s["tokens_in"]
        u["tokens_out"] += s["tokens_out"]
        cost = None if reprice else s.get("cost_usd")
        if cost is None and prices:
            cost = usd(
                s["model"],
                s["tokens_in"],
                s["tokens_out"],
                prices,
                s.get("tokens_cached"),
            )
        u["cost_usd"] = (
            None if cost is None or u["cost_usd"] is None else u["cost_usd"] + cost
        )
    return out


def last_attempt(trace: dict) -> list[dict]:
    """The steps of the runner's final attempt: what checks look at (D-019). Empty if that attempt recorded none."""
    last = trace.get("last_attempt")
    if last is None:
        last = max((s.get("run_attempt", 0) for s in trace["steps"]), default=0)
    return [s for s in trace["steps"] if s.get("run_attempt", 0) == last]
