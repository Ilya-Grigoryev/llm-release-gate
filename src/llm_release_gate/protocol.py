"""The protocol between the gate and an application: `protocol.schema.json` is its only definition (docs/protocol.md)."""

import json
from pathlib import Path
from typing import Any

import jsonschema

SCHEMA = json.loads((Path(__file__).parent / "protocol.schema.json").read_text())
PROTOCOL = SCHEMA["$defs"]["request"]["properties"]["protocol"]["const"]

# JSON's numbers only: JSON Schema counts 3.0 as an integer (a token count must be written 3) and a Decimal as a number
Validator = jsonschema.validators.extend(
    jsonschema.Draft202012Validator,
    type_checker=jsonschema.Draft202012Validator.TYPE_CHECKER.redefine_many(
        {
            "integer": lambda _, value: type(value) is int,
            "number": lambda _, value: type(value) in (int, float),
        }
    ),
)
VALIDATORS = {
    name: Validator(SCHEMA | {"$ref": f"#/$defs/{name}"}) for name in SCHEMA["$defs"]
}


def errors(instance: Any, part: str, at: str = "") -> list[str]:
    """What breaks the schema's `part` (request, answer, trace, step), each with the path to the field from `at`."""
    return describe(VALIDATORS[part], instance, at)


def describe(validator: Any, instance: Any, at: str = "") -> list[str]:
    found = []
    for e in validator.iter_errors(instance):
        where = ".".join(str(p) for p in (*([at] if at else []), *e.absolute_path))
        if e.validator == "required":
            found += [
                f"missing {where + '.' if where else ''}{k}"
                for k in e.validator_value
                if k not in e.instance
            ]
        else:
            found.append(f"{where}: {e.message}" if where else e.message)
    return sorted(set(found))
