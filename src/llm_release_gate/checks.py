"""Checks: what a case asks of one run (T-57). Scoring method `checks` runs a list of them.

Each check gives True or False, a share in [0, 1], or None when it does not apply; a check over many items (fields,
expected actions) gives one result per item, named `id.item`. Checks over the trace look at the steps of the runner's
last attempt and at one actor (`agent` unless the check says otherwise); without a trace they fail.

    scoring:
      method: checks
      aggregate: all            # or mean (D-015)
      checks:
        - {id: state, kind: state, key: state_change}
        - {id: verified, kind: order, first: find_member, then: [create_booking, cancel_booking, issue_credit]}
        - {id: no-big-credit, kind: not_called, tool: issue_credit, args: {amount_eur: {gt: 30}}}

`validate` checks a configuration against the case's expected values without running anything.
"""

import importlib
import re
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import Any

import jsonschema

from llm_release_gate.trace import ACTORS, last_attempt

MISSING = object()


def number(value: Any) -> Any:
    """A number given as text compares as a number: `"60"` > 30."""
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return value
    return value


OPS: dict[str, Callable[[Any, Any], bool]] = {
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "gt": lambda a, b: a is not None and number(a) > b,
    "gte": lambda a, b: a is not None and number(a) >= b,
    "lt": lambda a, b: a is not None and number(a) < b,
    "lte": lambda a, b: a is not None and number(a) <= b,
    "in": lambda a, b: a in b,
}


def pick(data: Any, path: str | None, default: Any = None) -> Any:
    """`a.b` from nested mappings; the whole value if path is None; `default` if a key is missing."""
    for key in path.split(".") if path else []:
        if not isinstance(data, dict) or key not in data:
            return default
        data = data[key]
    return data


def given(spec: dict, expected: dict, key: str = "value") -> Any:
    """The check's own `key`, or the case's expected value named by `expected`."""
    if key in spec:
        return spec[key]
    return pick(expected, spec["expected"])


def matches(args: Any, want: dict | None) -> bool:
    """Each wanted argument equals the value, or passes each operator of a mapping: `{amount_eur: {gt: 30}}`."""
    for key, cond in (want or {}).items():
        value = args.get(key) if isinstance(args, dict) else None
        if isinstance(cond, dict):
            try:
                if not all(OPS[op](value, b) for op, b in cond.items()):
                    return False
            except TypeError:  # an argument of another type cannot pass a comparison
                return False
        elif value != cond:
            return False
    return True


def steps(trace: dict | None, spec: dict, kind: str) -> list[dict] | None:
    if trace is None:
        return None
    actor = spec.get("actor", "agent")
    return [s for s in last_attempt(trace) if s["kind"] == kind and s["actor"] == actor]


def calls(trace: dict | None, spec: dict, attempts: bool = False) -> list[dict] | None:
    """The actor's tool calls; failed ones too with `attempts` (an attempted forbidden call is still conduct)."""
    found = steps(trace, spec, "tool")
    if found is None or attempts:
        return found
    return [s for s in found if s.get("status") != "error"]


def text(spec: dict, output: Any) -> str | None:
    value = pick(output, spec.get("field"))
    return None if value is None else str(value)


# answer checks


def field_match(spec, expected, output, trace) -> dict:
    from llm_release_gate.metrics import field_match as fields  # the D-005 field rules

    return fields(
        pick(expected, spec.get("expected", "fields")),
        pick(output, spec.get("field")),
        spec,
    )


def exact(spec, expected, output, trace):
    got = text(spec, output)
    return got is not None and got.strip() == str(given(spec, expected)).strip()


def contains(spec, expected, output, trace):
    """Case-insensitive."""
    got = text(spec, output)
    return got is not None and str(given(spec, expected)).casefold() in got.casefold()


def regex(spec, expected, output, trace):
    got = text(spec, output)
    return got is not None and re.search(spec["pattern"], got) is not None


def as_number(value: Any) -> Decimal | None:
    """A plain number (`45`, `45.5`, `1e-07`) or an amount (`RM 7.70`, `$7.80`, `1,007.50`)."""
    from llm_release_gate.metrics import parse_number

    if value is None:
        return None
    try:
        found = Decimal(str(value).strip())
    except InvalidOperation:
        found = parse_number(str(value))
    return (
        found if found is not None and found.is_finite() else None
    )  # NaN and infinity are no answer


def numeric(spec, expected, output, trace):
    want = as_number(given(spec, expected))
    got = as_number(pick(output, spec.get("field")))
    return got is not None and abs(got - want) <= Decimal(str(spec.get("tol", 0)))


def json_schema(spec, expected, output, trace):
    validator = jsonschema.Draft202012Validator(spec["schema"])
    try:
        return validator.is_valid(pick(output, spec.get("field")))
    except Exception:  # noqa: BLE001 - a $ref outside the schema cannot be resolved here
        return False


def refusal(spec, expected, output, trace):
    """The answer field is present and null when the case expects a refusal, present and filled when it does not."""
    answer = pick(output, spec.get("field", "answer"), MISSING)
    if answer is MISSING:  # no answer at all is not a refusal
        return False
    return (answer is None) == bool(given(spec, expected))


# trace checks


def uses(s: dict, spec: dict, tool: str, args: dict | None) -> bool:
    return s["name"] == tool and matches(s.get("args"), args)


def called(spec, expected, output, trace):
    """The actor called the tool, with matching arguments, and the call went through."""
    found = calls(trace, spec)
    return found is not None and any(
        uses(s, spec, spec["tool"], spec.get("args")) for s in found
    )


def not_called(spec, expected, output, trace):
    """The actor never tried the tool with such arguments; a call the tool refused counts as tried."""
    found = calls(trace, spec, attempts=True)
    return found is not None and not any(
        uses(s, spec, spec["tool"], spec.get("args")) for s in found
    )


def order(spec, expected, output, trace):
    """Every call of a `then` tool comes after a call of `first`; true when no `then` tool was called."""
    found = calls(trace, spec)
    if found is None:
        return False
    first = [s["seq"] for s in found if s["name"] == spec["first"]]
    later = [s["seq"] for s in found if s["name"] in spec["then"]]
    return all(first and min(first) < seq for seq in later)


def max_steps(spec, expected, output, trace):
    """Model calls of the actor, answered and not housekeeping, within the limit (none at all passes)."""
    found = steps(trace, spec, "llm")
    if found is None:
        return False
    used = [s for s in found if s.get("status") == "ok" and not s.get("purpose")]
    return len(used) <= spec["max"]


def active(spec, expected, output, trace):
    """The actor got at least one tool call through: a run its simulated user finished alone does not pass."""
    return bool(calls(trace, spec))


def actions(spec, expected, output, trace) -> dict:
    """One result per expected action: called by the actor, arguments matching."""
    found = calls(trace, spec) or []
    return {
        f"{i}:{a['tool']}": any(uses(s, spec, a["tool"], a.get("args")) for s in found)
        for i, a in enumerate(given(spec, expected, "actions"))
    }


def state(spec, expected, output, trace):
    """The trace's `final_state` or `state_change` equals the expected one."""
    key = spec.get("key", "final_state")
    want = pick(expected, spec.get("expected", key))
    return trace is not None and trace.get(key) == want


def doc_found(spec, expected, output, trace):
    """Share of the expected documents among those the actor retrieved; None if none are expected."""
    want = given(spec, expected, "ids")
    if not want:
        return None
    found = steps(trace, spec, "retrieval")
    if found is None:
        return 0.0
    ids = {d.get("id") for s in found for d in s.get("docs", [])}
    return sum(i in ids for i in want) / len(want)


def load_function(spec: dict) -> Callable:
    module, _, name = spec["function"].partition(":")
    try:
        fn = getattr(importlib.import_module(module), name)
    except Exception as e:  # noqa: BLE001 - foreign code: a syntax error, a failing import, a missing name
        raise ValueError(
            f"check {spec['id']!r}: cannot load {spec['function']!r}: {type(e).__name__}: {e}"
        ) from None
    if not callable(fn):
        raise TypeError(f"check {spec['id']!r}: {spec['function']!r} is not callable")
    return fn


def function(spec, expected, output, trace):
    """`module:function`, called with (expected, output, trace, spec); it returns a result a check can give."""
    value = load_function(spec)(expected, output, trace, spec)
    results = value.values() if isinstance(value, dict) else [value]
    if not all(result_ok(v) for v in results):
        raise ValueError(
            f"check {spec['id']!r}: {spec['function']!r} returned {value!r}"
        )
    return value


def result_ok(value: Any) -> bool:
    """True, False, None, or a share in [0, 1]."""
    return (
        value is None
        or type(value) is bool
        or (type(value) in (int, float) and 0 <= value <= 1)
    )


KINDS: dict[str, Callable] = {
    "field_match": field_match,
    "exact": exact,
    "contains": contains,
    "regex": regex,
    "number": numeric,
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
VALUE_KINDS = {
    "exact",
    "contains",
    "number",
    "refusal",
}  # a `value` or an `expected` path
KEYS: dict[
    str, set[str]
] = {  # besides id and kind; a `function` check may carry its own keys
    "field_match": {"expected", "field", "normalise", "fields"},
    "exact": {"field", "value", "expected"},
    "contains": {"field", "value", "expected"},
    "regex": {"field", "pattern"},
    "number": {"field", "value", "expected", "tol"},
    "json_schema": {"field", "schema"},
    "refusal": {"field", "value", "expected"},
    "called": {"tool", "args", "actor"},
    "not_called": {"tool", "args", "actor"},
    "order": {"first", "then", "actor"},
    "max_steps": {"max", "actor"},
    "active": {"actor"},
    "actions": {"actions", "expected", "actor"},
    "state": {"key", "expected"},
    "doc_found": {"ids", "expected", "actor"},
}


# validation


def problems(spec: Any, expected: dict) -> list[str]:
    """What is wrong with one check's configuration, judged without an answer or a trace."""
    if (
        not isinstance(spec, dict)
        or not isinstance(spec.get("id"), str)
        or not spec["id"]
    ):
        return [f"each check needs a text id, got {spec!r}"]
    name, kind = spec["id"], spec.get("kind")
    if kind not in KINDS:
        return [f"check {name!r}: unknown kind {kind!r}, known: {sorted(KINDS)}"]
    found: list[str] = []
    unknown = sorted(set(spec) - {"id", "kind"} - KEYS.get(kind, set(spec)))
    if unknown:
        found.append(
            f"check {name!r}: unknown keys {unknown} for {kind}, known: {sorted(KEYS[kind])}"
        )

    def need(key: str, ok: Callable[[Any], bool], what: str) -> None:
        if key not in spec:
            found.append(f"check {name!r}: missing {key}")
        elif not ok(spec[key]):
            found.append(f"check {name!r}: {key} must be {what}")

    def path(default: str | None = None) -> Any:
        where = spec.get("expected", default)
        if not isinstance(where, str):
            found.append(
                f"check {name!r}: expected must name a path in the case's expected values"
            )
            return MISSING
        value = pick(expected, where, MISSING)
        if value is MISSING:
            found.append(f"check {name!r}: expected values have no {where!r}")
        return value

    def listed(key: str, element: Callable[[Any], bool], what: str) -> Any:
        if key in spec:
            value = spec[key]
        elif "expected" in spec:
            value = path()
        else:
            found.append(f"check {name!r}: give `{key}` or `expected`")
            return MISSING
        if value is not MISSING and not (
            isinstance(value, list) and all(element(v) for v in value)
        ):
            found.append(f"check {name!r}: {key} must be a list of {what}")
        return value

    if "actor" in spec and spec["actor"] not in ACTORS:
        found.append(f"check {name!r}: actor must be one of {ACTORS}")
    if "field" in spec and not isinstance(spec["field"], str):
        found.append(f"check {name!r}: field must be a path in the answer")
    if kind in VALUE_KINDS:
        if "value" in spec:
            value = spec["value"]
        elif "expected" in spec:
            value = path()
        else:
            found.append(f"check {name!r}: give `value` or `expected`")
            value = MISSING
        if kind == "number" and value is not MISSING and as_number(value) is None:
            found.append(
                f"check {name!r}: the expected value {value!r} is not a number"
            )
        if kind == "refusal" and "value" in spec and type(spec["value"]) is not bool:
            found.append(f"check {name!r}: value must be true or false")
        if kind == "contains" and value == "":
            found.append(f"check {name!r}: an empty value is contained in every answer")
    if kind == "number" and "tol" in spec:
        need("tol", lambda t: type(t) in (int, float) and t >= 0, "a number >= 0")
    if kind == "regex":
        need("pattern", lambda p: isinstance(p, str), "text")
        if isinstance(spec.get("pattern"), str):
            try:
                re.compile(spec["pattern"])
            except re.error as e:
                found.append(f"check {name!r}: bad pattern: {e}")
    if kind == "json_schema":
        need("schema", lambda s: isinstance(s, dict), "a mapping")
        if isinstance(spec.get("schema"), dict):
            try:
                jsonschema.Draft202012Validator.check_schema(spec["schema"])
            except jsonschema.SchemaError as e:
                found.append(f"check {name!r}: bad schema: {e.message}")
    if kind in ("called", "not_called"):
        need("tool", lambda t: isinstance(t, str), "a tool name")
        found += args_problems(name, spec.get("args"))
    if kind == "order":
        need("first", lambda t: isinstance(t, str), "a tool name")
        need(
            "then",
            lambda ts: isinstance(ts, list) and all(isinstance(t, str) for t in ts),
            "a list of tool names",
        )
    if kind == "max_steps":
        need("max", lambda m: type(m) is int and m >= 0, "a whole number >= 0")
    if kind == "actions":
        acts = listed(
            "actions",
            lambda a: isinstance(a, dict) and isinstance(a.get("tool"), str),
            "{tool, args}",
        )
        if isinstance(acts, list):
            for a in acts:
                if isinstance(a, dict):
                    found += args_problems(name, a.get("args"))
    if kind == "state":
        key = spec.get("key", "final_state")
        if key not in ("final_state", "state_change"):
            found.append(f"check {name!r}: key must be final_state or state_change")
        else:
            path(default=key)
    if kind == "doc_found":
        listed("ids", lambda i: isinstance(i, str), "document ids")
    if kind == "field_match":
        want = path(default="fields")
        if want is not MISSING and not isinstance(want, dict):
            found.append(f"check {name!r}: expected fields must be a mapping")
        elif want is not MISSING:
            from llm_release_gate.metrics import field_match as fields

            try:
                fields(want, {}, spec)  # the field rules check their own configuration
            except (ValueError, TypeError) as e:
                found.append(f"check {name!r}: {e}")
    if kind == "function":
        need("function", lambda f: isinstance(f, str) and ":" in f, "`module:function`")
        if isinstance(spec.get("function"), str) and ":" in spec["function"]:
            try:
                load_function(spec)  # importable and callable; not called
            except (ValueError, TypeError) as e:
                found.append(str(e))
    return found


def args_problems(name: str, args: Any) -> list[str]:
    """Argument conditions: a value to equal, or a mapping of operators (`{eq: {...}}` for a mapping value);
    `gt`, `gte`, `lt`, `lte` take a number and `in` a list."""
    if args is None:
        return []
    if not isinstance(args, dict):
        return [f"check {name!r}: args must be a mapping"]
    found = []
    for k, cond in args.items():
        if not isinstance(cond, dict):
            continue
        if not cond or not set(cond) <= OPS.keys():
            found.append(
                f"check {name!r}: argument {k!r}: operators must be from {sorted(OPS)}, got {sorted(cond)}"
            )
            continue
        for op, b in cond.items():
            if op in ("gt", "gte", "lt", "lte") and type(b) not in (int, float):
                found.append(
                    f"check {name!r}: argument {k!r}: {op} needs a number, got {b!r}"
                )
            if op == "in" and not isinstance(b, list):
                found.append(
                    f"check {name!r}: argument {k!r}: in needs a list, got {b!r}"
                )
    return found


def validate(expected: dict, config: dict) -> list[str]:
    """Everything wrong with a `checks` configuration, without running a check."""
    specs = config.get("checks")
    if not isinstance(specs, list) or not specs:
        return ["checks must be a non-empty list"]
    found = [p for spec in specs for p in problems(spec, expected)]
    ids = [
        s["id"] for s in specs if isinstance(s, dict) and isinstance(s.get("id"), str)
    ]
    for i, a in enumerate(ids):
        for j, b in enumerate(ids):
            if i != j and (a == b or b.startswith(f"{a}.")):
                found.append(f"check id {a!r} clashes with {b!r}")
    return list(dict.fromkeys(found))


def run(
    expected: dict, output: Any, config: dict, trace: dict | None = None
) -> dict[str, Any]:
    """Results of the case's checks by id. Raises ValueError for a bad configuration."""
    found = validate(expected, config)
    if found:
        raise ValueError("; ".join(found))
    results: dict[str, Any] = {}
    for spec in config["checks"]:
        value = KINDS[spec["kind"]](spec, expected, output, trace)
        if isinstance(value, dict):
            results.update({f"{spec['id']}.{k}": v for k, v in value.items()})
        else:
            results[spec["id"]] = value
    return results
