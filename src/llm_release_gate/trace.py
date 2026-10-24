"""What happened inside one run of a case, step by step (format: D-019).

The runner keeps one `Trace` per (case, repetition) and makes it current while the pipeline runs, so a run that fails
halfway still leaves the steps it paid for. An adapter records into it without touching the application:

    client = trace.openai_client(OpenAI())      # a step per model call
    world.call = trace.wrap_tool(world.call)    # a step per tool call
    trace.current().final_state = world.state()

Outside the runner `current()` is None and both wrappers just pass calls through.
"""

import contextlib
import contextvars
import json
import threading
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from llm_release_gate.prices import Prices, usd

VERSION = 1
KINDS = ("llm", "tool", "message", "retrieval")
ACTORS = ("agent", "user", "system", "env")
STATUSES = {"llm": ("ok", "error"), "tool": ("ok", "error", "unknown")}
FINISH = {
    "stop": "stop",
    "tool_calls": "tool_calls",
    "function_call": "tool_calls",
    "length": "length",
}

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
    """What makes a step break the format: missing required fields, unknown kind, actor or status."""
    found = []
    kind, status = step.get("kind"), step.get("status")
    if kind not in KINDS:
        found.append(f"kind must be one of {KINDS}")
    if step.get("actor") not in ACTORS:
        found.append(f"actor must be one of {ACTORS}")
    need = ["seq", "kind", "actor"]
    if kind in STATUSES:
        need.append("status")
        if status is not None and status not in STATUSES[kind]:
            found.append(f"{kind} status must be one of {STATUSES[kind]}")
    if kind == "llm" and status == "ok":
        need += ["model", "tokens_in", "tokens_out", "cost_usd"]
    if kind == "llm" and status == "error":
        need += ["error", "attempt"]
    if kind == "tool":
        need += ["name", "args"]
    found += [f"missing {k}" for k in need if k not in step]
    return found


class Trace:
    def __init__(self, prices: Prices | None = None):
        self.steps: list[dict] = []
        self.final_state: Any = None
        self.state_change: Any = None
        self.stop: str | None = None
        self.run_attempt = (
            0  # the runner's attempt; a retried run keeps the steps it paid for
        )
        self.native: list = []  # raw provider responses, written next to the record
        self.wall_s: float | None = None
        self.prices = prices or {}
        self.lock = threading.Lock()

    def step(self, kind: str, actor: str, **fields: Any) -> dict:
        """Add a step (the manual path). Raises ValueError if it breaks the format."""
        with self.lock:
            step = {
                "seq": len(self.steps),
                "kind": kind,
                "actor": actor,
                "ts": now(),
                **fields,
            }
            step["run_attempt"] = self.run_attempt
            found = problems(step)
            if found:
                raise ValueError(f"bad {kind} step: {'; '.join(found)}")
            self.steps.append(step)
            return step

    def failures(self, actor: str) -> int:
        """Failed model calls of `actor` at the end of the trace: how often the current call was already tried."""
        n = 0
        for s in reversed(self.steps):
            if s["kind"] != "llm" or s["actor"] != actor:
                continue
            if s["status"] != "error":
                break
            n += 1
        return n

    def empty(self) -> bool:
        return not self.steps and self.final_state is None and self.state_change is None

    def to_dict(self) -> dict:
        return {
            "v": VERSION,
            "steps": self.steps,
            "final_state": self.final_state,
            "state_change": self.state_change,
            "stop": self.stop,
        }


def usage(trace: dict, prices: Prices | None = None) -> dict[str, dict]:
    """Calls, tokens and USD per actor over every answered model call, abandoned attempts too: all were paid for.

    A step without a price is priced from `prices`; `cost_usd` is None if some call stays unpriced.
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
        cost = s.get("cost_usd")
        if cost is None and prices:
            cost = usd(s["model"], s["tokens_in"], s["tokens_out"], prices)
        u["cost_usd"] = (
            None if cost is None or u["cost_usd"] is None else u["cost_usd"] + cost
        )
    return out


def last_attempt(trace: dict) -> list[dict]:
    """The steps of the runner's final attempt: what checks look at (D-019)."""
    last = max((s.get("run_attempt", 0) for s in trace["steps"]), default=0)
    return [s for s in trace["steps"] if s.get("run_attempt", 0) == last]


def parse(text: Any) -> Any:
    """JSON if it parses, else the text as it came."""
    if not isinstance(text, str):
        return text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def field(obj: Any, name: str) -> Any:
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def ms(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)


class _Completions:
    def __init__(self, inner: Any, actor: str, trace: "Trace | None"):
        self.inner, self.actor, self.trace = inner, actor, trace

    def create(self, **request: Any) -> Any:
        t = self.trace or current()
        if t is None:
            return self.inner.create(**request)
        tool_results(t, request.get("messages") or [])
        ts, start = now(), time.perf_counter()
        try:
            r = self.inner.create(**request)
        except Exception as e:
            t.step(
                "llm",
                self.actor,
                ts=ts,
                latency_ms=ms(start),
                status="error",
                error=f"{type(e).__name__}: {e}",
                attempt=t.failures(self.actor) + 1,
            )
            raise
        t.step(
            "llm", self.actor, ts=ts, latency_ms=ms(start), **llm_fields(r, t.prices)
        )
        dump = getattr(r, "model_dump", None)
        if callable(dump):
            t.native.append(dump(mode="json"))
        return r


def openai_client(client: Any, actor: str = "agent", trace: Trace | None = None) -> Any:
    """`client` with `chat.completions.create` recording a step per call into the current trace (or `trace`).

    Tool steps the application did not record itself are rebuilt from the `tool` messages it sends back: their
    status is `unknown` and they carry no timing.
    """
    return _Client(client, _Completions(client.chat.completions, actor, trace))


class _Client:
    """The wrapped client: `chat.completions` records, everything else is the client's own."""

    def __init__(self, client: Any, completions: _Completions):
        self._client = client
        self.chat = SimpleNamespace(completions=completions)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


def llm_fields(r: Any, prices: Prices) -> dict:
    """A model step from an OpenAI chat completion: what the API reported, the new output only."""
    choice, used = r.choices[0], r.usage
    message = choice.message
    fields: dict[str, Any] = {
        "status": "ok",
        "model": r.model,
        "tokens_in": used.prompt_tokens,
        "tokens_out": used.completion_tokens,
        "tokens_cached": field(field(used, "prompt_tokens_details"), "cached_tokens")
        or 0,
        "tokens_reasoning": field(
            field(used, "completion_tokens_details"), "reasoning_tokens"
        )
        or 0,
        "cost_usd": usd(r.model, used.prompt_tokens, used.completion_tokens, prices)
        if prices
        else None,
        "finish_reason": FINISH.get(choice.finish_reason, "other"),
        "fingerprint": getattr(r, "system_fingerprint", None),
        "request_id": getattr(r, "id", None),
        "text": message.content,
    }
    calls = message.tool_calls or []
    if calls:
        fields["tool_calls"] = [
            {"id": c.id, "name": c.function.name, "args": parse(c.function.arguments)}
            for c in calls
        ]
    if choice.finish_reason not in FINISH:
        fields["extra"] = {"finish_reason": choice.finish_reason}
    return fields


def tool_results(t: Trace, messages: list) -> None:
    """Match the `tool` messages a request sends back to the calls a model step asked for.

    A call the application recorded itself (`wrap_tool`, no call id yet) gets the id; any other becomes a rebuilt step.
    """
    with t.lock:
        known = {s.get("call_id") for s in t.steps if s["kind"] == "tool"}
    for m in messages:
        call_id = field(m, "tool_call_id")
        if field(m, "role") != "tool" or not call_id or call_id in known:
            continue
        known.add(call_id)
        asked = next(
            (
                (i, s, c)
                for i, s in reversed(list(enumerate(t.steps)))
                if s["kind"] == "llm"
                for c in s.get("tool_calls", [])
                if c["id"] == call_id
            ),
            None,
        )
        if asked is None:
            continue  # a call from before the trace began
        i, llm_step, wanted = asked
        own = next(
            (
                s
                for s in t.steps[i + 1 :]
                if s["kind"] == "tool"
                and "call_id" not in s
                and s["name"] == wanted["name"]
                and s["actor"] == llm_step["actor"]
            ),
            None,
        )
        if own is not None:
            own["call_id"] = call_id
            continue
        t.step(
            "tool",
            llm_step["actor"],
            call_id=call_id,
            name=wanted["name"],
            args=wanted["args"],
            status="unknown",
            result=parse(field(m, "content")),
        )


def wrap_tool(
    call: Callable[[str, dict], Any], actor: str = "agent"
) -> Callable[[str, dict], Any]:
    """`call(name, args)` recording a step per tool call into the current trace; an exception is recorded and re-raised."""

    def traced(name: str, args: dict) -> Any:
        t = current()
        if t is None:
            return call(name, args)
        ts, start = now(), time.perf_counter()
        try:
            result = call(name, args)
        except Exception as e:
            t.step(
                "tool",
                actor,
                ts=ts,
                latency_ms=ms(start),
                name=name,
                args=args,
                status="error",
                error=str(e),
            )
            raise
        t.step(
            "tool",
            actor,
            ts=ts,
            latency_ms=ms(start),
            name=name,
            args=args,
            status="ok",
            result=result,
        )
        return result

    return traced
