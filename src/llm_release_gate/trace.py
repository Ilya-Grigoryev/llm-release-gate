"""What happened inside one run of a case, step by step (format: D-019).

The runner keeps one `Trace` per (case, repetition) and makes it current while the pipeline runs, so a run that fails
halfway still leaves the steps it paid for. An adapter records into it without touching the application:

    client = trace.openai_client(OpenAI())      # a step per model call
    world.call = trace.wrap_tool(world.call)    # a step per tool call
    if (t := trace.current()) is not None:
        t.final_state = world.state()

Outside the runner `current()` is None and both wrappers just pass calls through. Only `chat.completions.create` is
recorded; a streamed call leaves a note, and other methods (Responses API, `parse`, raw responses) pass through unrecorded. The current trace belongs to the
thread that runs the case: a call from a thread the application starts is recorded only with an explicit `trace=`.
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


def count(value: Any) -> bool:
    return type(value) is int and value >= 0


def problems(step: dict) -> list[str]:
    """What makes a step break the format: missing or mistyped required fields, unknown kind, actor or status."""
    found = []
    kind, status = step.get("kind"), step.get("status")
    if kind not in KINDS:
        found.append(f"kind must be one of {KINDS}")
    if not isinstance(step.get("ts"), str | None):
        found.append("ts must be a string or null")
    if step.get("actor") not in ACTORS:
        found.append(f"actor must be one of {ACTORS}")
    need = ["seq", "kind", "actor"]
    if kind in STATUSES:
        need.append("status")
        if status is not None and status not in STATUSES[kind]:
            found.append(f"{kind} status must be one of {STATUSES[kind]}")
    if kind == "llm" and status == "ok":
        need += ["model", "tokens_in", "tokens_out", "cost_usd"]
        for k in ("tokens_in", "tokens_out"):
            if k in step and not count(step[k]):
                found.append(f"{k} must be a whole number >= 0")
        cost = step.get("cost_usd")
        if cost is not None and (type(cost) not in (int, float) or cost < 0):
            found.append("cost_usd must be a number >= 0 or null")
    if kind == "llm" and status == "error":
        need += ["error", "attempt"]
        if "attempt" in step and not (count(step["attempt"]) and step["attempt"] >= 1):
            found.append("attempt must be a whole number >= 1")
    if kind == "tool":
        need += ["name", "args"]
    found += [f"missing {k}" for k in need if k not in step]
    return found


def plain(value: Any) -> Any:
    """`value` as JSON can hold it: what does not serialize becomes its repr."""
    return json.loads(json.dumps(value, default=repr))


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
        self.notes: list[str] = []  # calls that went unrecorded, and why
        self.wall_s: float | None = None
        self.prices = prices or {}
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

    def failures(self, actor: str) -> int:
        """Failed model calls of `actor` at the end of this attempt: how often the current call was already tried."""
        n = 0
        with self.lock:
            for s in reversed(self.steps):
                if s["run_attempt"] != self.run_attempt:
                    break
                if s["kind"] != "llm" or s["actor"] != actor:
                    continue
                if s["status"] != "error":
                    break
                n += 1
        return n

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

    def __getattr__(
        self, name: str
    ) -> Any:  # parse, with_raw_response, …: passed through unrecorded
        return getattr(self.inner, name)

    def create(self, **request: Any) -> Any:
        t = self.trace or current()
        if t is None:
            return self.inner.create(**request)
        messages = request.get("messages")
        if messages is not None and not isinstance(messages, (list, tuple)):
            request["messages"] = messages = list(
                messages
            )  # read it once, for us and the provider
        tool_results(t, messages or [])
        if request.get("stream"):
            t.notes.append(f"{self.actor}: a streamed call is not recorded")
            return self.inner.create(**request)
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
        try:
            fields = llm_fields(r, t.prices)
            t.step("llm", self.actor, ts=ts, latency_ms=ms(start), **fields)
        except Exception as e:  # noqa: BLE001 - an odd response must not break the application
            t.notes.append(
                f"{self.actor}: a call is not recorded ({type(e).__name__}: {e})"
            )
            return r
        if getattr(r, "usage", None) is None:
            t.notes.append(
                f"{self.actor}: a call reported no usage; its tokens and cost count as 0"
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
    """The wrapped client: `chat.completions.create` records, everything else is the client's own."""

    def __init__(self, client: Any, completions: _Completions):
        self._client = client
        self.chat = SimpleNamespace(completions=completions)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


def llm_fields(r: Any, prices: Prices) -> dict:
    """A model step from an OpenAI chat completion: what the API reported, the new output only."""
    choice, used = r.choices[0], getattr(r, "usage", None)
    tokens_in = field(used, "prompt_tokens") or 0  # a provider may report no usage
    tokens_out = field(used, "completion_tokens") or 0
    cached = field(field(used, "prompt_tokens_details"), "cached_tokens") or 0
    finish = getattr(choice, "finish_reason", None)
    message = choice.message
    fields: dict[str, Any] = {
        "status": "ok",
        "model": r.model,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "tokens_cached": cached,
        "tokens_reasoning": field(
            field(used, "completion_tokens_details"), "reasoning_tokens"
        )
        or 0,
        "cost_usd": usd(r.model, tokens_in, tokens_out, prices, cached)
        if prices
        else None,
        "finish_reason": FINISH.get(finish, "other"),
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
    if finish not in FINISH:
        fields["extra"] = {"finish_reason": finish}
    return fields


def tool_results(t: Trace, messages: list) -> None:
    """Match the `tool` messages a request sends back to the calls a model step of this attempt asked for.

    A call the application recorded itself (`wrap_tool`, no call id yet) gets the id; any other becomes a rebuilt step.
    Only the runner's current attempt counts, so a retried run that reuses call ids still gets its own steps.
    """
    with t.lock:
        mine = [
            (i, s) for i, s in enumerate(t.steps) if s["run_attempt"] == t.run_attempt
        ]
        known = {s.get("call_id") for _, s in mine if s["kind"] == "tool"}
        for m in messages:
            call_id = field(m, "tool_call_id")
            if field(m, "role") != "tool" or not call_id or call_id in known:
                continue
            known.add(call_id)
            asked = next(
                (
                    (i, s, c)
                    for i, s in reversed(mine)
                    if s["kind"] == "llm"
                    for c in s.get("tool_calls", [])
                    if c["id"] == call_id
                ),
                None,
            )
            if asked is None:
                continue  # a call from before this attempt began
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
                ts=None,
                call_id=call_id,
                name=wanted["name"],
                args=wanted["args"],
                status="unknown",
                result=plain(parse(field(m, "content"))),
            )
            mine = [
                (i, s)
                for i, s in enumerate(t.steps)
                if s["run_attempt"] == t.run_attempt
            ]


def wrap_tool(
    call: Callable[[str, dict], Any], actor: str = "agent", trace: Trace | None = None
) -> Callable[[str, dict], Any]:
    """`call(name, args)` recording a step per tool call into the current trace (or `trace`).

    An exception is recorded and re-raised; a result JSON cannot hold is recorded as its repr.
    """

    def traced(name: str, args: dict) -> Any:
        t = trace or current()
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
                args=plain(args),
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
            args=plain(args),
            status="ok",
            result=plain(result),
        )
        return result

    return traced
