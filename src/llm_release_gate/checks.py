"""Checks: what a case asks of one run (T-57). Scoring method `checks` runs a list of them.

Each check gives True or False, a share in [0, 1], or None when it does not apply; a check over many items (fields,
expected actions) gives one result per item. Checks over the trace look at the steps of the runner's last attempt
and at one actor (`agent` unless the check says otherwise); without a trace they fail.

    scoring:
      method: checks
      aggregate: all            # or mean (D-015)
      checks:
        - {id: state, kind: state, key: state_change}
        - {id: verified, kind: order, first: find_member, then: [create_booking, cancel_booking, issue_credit]}
        - {id: no-big-credit, kind: not_called, tool: issue_credit, args: {amount_eur: {gt: 30}}}
"""

import importlib
import re
from collections.abc import Callable
from typing import Any

import jsonschema

from llm_release_gate.trace import last_attempt

OPS: dict[str, Callable[[Any, Any], bool]] = {
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "gt": lambda a, b: a is not None and a > b,
    "gte": lambda a, b: a is not None and a >= b,
    "lt": lambda a, b: a is not None and a < b,
    "lte": lambda a, b: a is not None and a <= b,
    "in": lambda a, b: a in b,
}


def need(spec: dict, *keys: str) -> None:
    missing = [k for k in keys if k not in spec]
    if missing:
        raise ValueError(f"check {spec.get('id')!r}: missing {', '.join(missing)}")


def pick(data: Any, path: str | None) -> Any:
    """`a.b` from nested mappings; the whole value if path is None; None if any key is missing."""
    for key in (path or "").split(".") if path else []:
        data = data.get(key) if isinstance(data, dict) else None
    return data


def given(spec: dict, expected: dict, key: str = "value") -> Any:
    """The check's own `value`, or the case's expected value named by `expected`."""
    if key in spec:
        return spec[key]
    if "expected" in spec:
        return pick(expected, spec["expected"])
    raise ValueError(f"check {spec.get('id')!r}: give `{key}` or `expected`")


def matches(args: Any, want: dict | None) -> bool:
    """Arguments match when each wanted key equals, or passes each operator: `{amount_eur: {gt: 30}}`."""
    for key, cond in (want or {}).items():
        value = args.get(key) if isinstance(args, dict) else None
        if isinstance(cond, dict) and cond and set(cond) <= OPS.keys():
            try:
                if not all(OPS[op](value, b) for op, b in cond.items()):
                    return False
            except TypeError:  # comparing a string with a number
                return False
        elif value != cond:
            return False
    return True


def steps(trace: dict | None, spec: dict, kind: str) -> list[dict] | None:
    if trace is None:
        return None
    actor = spec.get("actor", "agent")
    return [s for s in last_attempt(trace) if s["kind"] == kind and s["actor"] == actor]


def calls(trace: dict | None, spec: dict) -> list[dict] | None:
    found = steps(trace, spec, "tool")
    return None if found is None else [s for s in found if s.get("status") != "error"]


# answer checks


def field_match(spec: dict, expected: dict, output: Any, trace: dict | None) -> dict:
    from llm_release_gate.metrics import field_match as fields  # the D-005 field rules

    want = pick(expected, spec.get("expected", "fields"))
    if not isinstance(want, dict):
        raise TypeError(f"check {spec.get('id')!r}: expected fields must be a mapping")
    return fields(want, pick(output, spec.get("field")), spec)


def text(spec: dict, output: Any) -> str | None:
    value = pick(output, spec.get("field"))
    return None if value is None else str(value)


def exact(spec, expected, output, trace):
    want = str(
        given(spec, expected)
    ).strip()  # first: a bad config fails even without an answer
    got = text(spec, output)
    return got is not None and got.strip() == want


def contains(spec, expected, output, trace):
    want = str(given(spec, expected))
    got = text(spec, output)
    return got is not None and want.casefold() in got.casefold()


def regex(spec, expected, output, trace):
    need(spec, "pattern")
    pattern = re.compile(spec["pattern"])
    got = text(spec, output)
    return got is not None and pattern.search(got) is not None


def number(spec, expected, output, trace):
    from llm_release_gate.metrics import parse_number

    want = parse_number(str(given(spec, expected)))
    if want is None:
        raise ValueError(f"check {spec.get('id')!r}: expected value is not a number")
    got = text(spec, output)
    value = parse_number(got) if got is not None else None
    return value is not None and abs(value - want) <= type(want)(
        str(spec.get("tol", 0))
    )


def json_schema(spec, expected, output, trace):
    need(spec, "schema")
    jsonschema.Draft202012Validator.check_schema(spec["schema"])
    return jsonschema.Draft202012Validator(spec["schema"]).is_valid(
        pick(output, spec.get("field"))
    )


def refusal(spec, expected, output, trace):
    """The answer field is null when the case expects a refusal, and filled when it does not."""
    should = bool(given(spec, expected))
    return (pick(output, spec.get("field", "answer")) is None) == should


# trace checks


def called(spec, expected, output, trace):
    need(spec, "tool")
    found = calls(trace, spec)
    if found is None:
        return False
    return any(
        s["name"] == spec["tool"] and matches(s.get("args"), spec.get("args"))
        for s in found
    )


def not_called(spec, expected, output, trace):
    need(spec, "tool")
    found = calls(trace, spec)
    if found is None:
        return False
    return not any(
        s["name"] == spec["tool"] and matches(s.get("args"), spec.get("args"))
        for s in found
    )


def order(spec, expected, output, trace):
    """Every call of a `then` tool comes after a call of `first`; true when no `then` tool was called."""
    need(spec, "first", "then")
    found = calls(trace, spec)
    if found is None:
        return False
    first = [s["seq"] for s in found if s["name"] == spec["first"]]
    later = [s["seq"] for s in found if s["name"] in spec["then"]]
    return all(first and min(first) < seq for seq in later)


def max_steps(spec, expected, output, trace):
    """Model calls of the actor, answered and not housekeeping, within the limit."""
    need(spec, "max")
    found = steps(trace, spec, "llm")
    if found is None:
        return False
    used = [s for s in found if s.get("status") == "ok" and not s.get("purpose")]
    return len(used) <= spec["max"]


def active(spec, expected, output, trace):
    """The actor called at least one tool: a run its simulated user finished alone does not pass."""
    found = calls(trace, spec)
    return bool(found)


def actions(spec, expected, output, trace) -> dict:
    """One result per expected action: called by the actor, arguments matching."""
    want = given(spec, expected, "actions")
    if not isinstance(want, list):
        raise TypeError(f"check {spec.get('id')!r}: actions must be a list")
    found = calls(trace, spec) or []
    return {
        f"{i}:{a['tool']}": any(
            s["name"] == a["tool"] and matches(s.get("args"), a.get("args"))
            for s in found
        )
        for i, a in enumerate(want)
    }


def state(spec, expected, output, trace):
    """The trace's `final_state` or `state_change` equals the expected one."""
    key = spec.get("key", "final_state")
    if key not in ("final_state", "state_change"):
        raise ValueError(
            f"check {spec.get('id')!r}: key must be final_state or state_change"
        )
    want = pick(expected, spec.get("expected", key))
    return trace is not None and trace.get(key) == want


def doc_found(spec, expected, output, trace):
    """Share of the expected documents among those the actor retrieved."""
    want = given(spec, expected, "ids")
    if not want:
        return None
    found = steps(trace, spec, "retrieval")
    if found is None:
        return 0.0
    ids = {d.get("id") for s in found for d in s.get("docs", [])}
    return sum(i in ids for i in want) / len(want)


def function(spec, expected, output, trace):
    """`module:function`, called with (expected, output, trace, spec)."""
    need(spec, "function")
    module, _, name = spec["function"].partition(":")
    try:
        fn = getattr(importlib.import_module(module), name)
    except (ImportError, AttributeError, ValueError) as e:
        raise ValueError(
            f"check {spec.get('id')!r}: cannot load {spec['function']!r}: {e}"
        ) from None
    return fn(expected, output, trace, spec)


KINDS: dict[str, Callable] = {
    "field_match": field_match,
    "exact": exact,
    "contains": contains,
    "regex": regex,
    "number": number,
    "json_schema": json_schema,
    "refusal": refusal,
    "called": called,
    "not_called": not_called,
    "order": order,
    "max_steps": max_steps,
    "active": active,
    "actions": actions,
    "state": state,
    "doc_found": doc_found,
    "function": function,
}


def run(
    expected: dict, output: Any, config: dict, trace: dict | None = None
) -> dict[str, Any]:
    """Results of the case's checks by id; a check with several items gives `id.item` per item."""
    specs = config.get("checks")
    if not isinstance(specs, list) or not specs:
        raise ValueError("checks must be a non-empty list")
    results: dict[str, Any] = {}
    for spec in specs:
        if not isinstance(spec, dict) or "id" not in spec or "kind" not in spec:
            raise ValueError(f"each check needs an id and a kind, got {spec!r}")
        if spec["kind"] not in KINDS:
            raise ValueError(
                f"check {spec['id']!r}: unknown kind {spec['kind']!r}, known: {sorted(KINDS)}"
            )
        if spec["id"] in results or any(
            k.startswith(f"{spec['id']}.") for k in results
        ):
            raise ValueError(f"check id {spec['id']!r} used twice")
        value = KINDS[spec["kind"]](spec, expected, output, trace)
        if isinstance(value, dict):
            results.update({f"{spec['id']}.{k}": v for k, v in value.items()})
        else:
            results[spec["id"]] = value
    return results
