"""The protocol between the gate and an application: `protocol.schema.json` is its only definition (docs/protocol.md)."""

import json
from pathlib import Path
from typing import Any

import jsonschema

PROTOCOL = 1
SCHEMA = json.loads((Path(__file__).parent / "protocol.schema.json").read_text())

# JSON Schema counts 3.0 as an integer; a token count or an attempt number must be written as 3
Validator = jsonschema.validators.extend(
    jsonschema.Draft202012Validator,
    type_checker=jsonschema.Draft202012Validator.TYPE_CHECKER.redefine(
        "integer", lambda _, value: type(value) is int
    ),
)
VALIDATORS = {
    name: Validator(SCHEMA | {"$ref": f"#/$defs/{name}"}) for name in SCHEMA["$defs"]
}


def errors(instance: Any, part: str) -> list[str]:
    """What breaks the schema's `part` (request, answer, trace, step), each with the path to the field."""
    found = []
    for e in VALIDATORS[part].iter_errors(instance):
        where = ".".join(str(p) for p in e.absolute_path)
        if e.validator == "required":
            found += [
                f"missing {where + '.' if where else ''}{k}"
                for k in e.validator_value
                if k not in e.instance
            ]
        else:
            found.append(f"{where}: {e.message}" if where else e.message)
    return sorted(set(found))
