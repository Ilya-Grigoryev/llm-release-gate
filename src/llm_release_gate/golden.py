"""Golden set on disk: one YAML file per case, inputs referenced by path relative to it."""

import argparse
import json
import sys
from pathlib import Path

import jsonschema
import yaml

from llm_release_gate.hashing import canonical_hash, file_hash
from llm_release_gate.metrics import problems
from llm_release_gate.pipeline import Case

SCHEMA = json.loads((Path(__file__).parent / "case.schema.json").read_text())


def case_files(directory: Path) -> list[Path]:
    return sorted(p for p in Path(directory).iterdir() if p.suffix in (".yaml", ".yml"))


def to_case(path: Path, raw: dict) -> Case:
    return Case(
        id=raw["id"],
        inputs={name: path.parent / ref for name, ref in raw["input"].items()},
        expected=raw["expected"],
        scoring=raw["scoring"],
    )


def load_cases(directory: Path) -> list[Case]:
    return [to_case(p, yaml.safe_load(p.read_text())) for p in case_files(directory)]


def validate(directory: Path) -> tuple[str | None, list[str]]:
    """Check every case file and its scoring; return (set hash, errors). The hash is None if there are errors.

    The set hash covers each case's parsed content and the bytes of each input,
    so reformatting a YAML file keeps it and editing an expectation or an input changes it.
    """
    errors, seen, parts = [], {}, {}
    files = case_files(directory)
    if not files:
        return None, [f"{directory}: no *.yaml cases"]
    root = Path(directory).resolve()
    for path in files:
        try:
            raw = yaml.safe_load(path.read_text())
            jsonschema.validate(raw, SCHEMA)
            case_hash = canonical_hash(raw)
        except OSError as e:  # a link to nothing, say
            errors.append(f"{path.name}: {e.strerror}")
            continue
        except (yaml.YAMLError, UnicodeDecodeError, jsonschema.ValidationError) as e:
            errors.append(f"{path.name}: {getattr(e, 'message', e)}")
            continue
        except TypeError:
            errors.append(f"{path.name}: non-JSON value, quote dates and times")
            continue
        found = problems(raw["expected"], raw["scoring"])
        if found:
            errors.append(f"{path.name}: scoring: {'; '.join(found)}")
            continue
        if raw["id"] in seen:
            errors.append(f"{path.name}: id {raw['id']} also in {seen[raw['id']]}")
            continue
        seen[raw["id"]] = path.name
        case = to_case(path, raw)
        outside = [
            str(p) for p in case.inputs.values() if not p.resolve().is_relative_to(root)
        ]
        if outside:
            errors.append(f"{path.name}: input outside the set {', '.join(outside)}")
            continue
        missing = [str(p) for p in case.inputs.values() if not p.is_file()]
        if missing:
            errors.append(f"{path.name}: missing input {', '.join(missing)}")
            continue
        parts[case.id] = {
            "case": case_hash,
            "inputs": {name: file_hash(p) for name, p in case.inputs.items()},
        }
    return (None if errors else canonical_hash(parts)), errors


def case_hashes(directory: Path) -> dict[str, dict]:
    """Each case's id with the hash of its content and those of its inputs (None: unreadable), without checking the
    case: for naming what a request changes. A file that does not parse is left out."""

    def readable(path: Path) -> str | None:
        try:
            return file_hash(path)
        except OSError:  # an input out of git, fetched in one checkout only
            return None

    found = {}
    for path in case_files(directory):
        try:
            raw = yaml.safe_load(path.read_text())
            inputs = {
                n: readable(path.parent / f) for n, f in dict(raw["input"]).items()
            }
            found[str(raw["id"])] = {"case": canonical_hash(raw), "inputs": inputs}
        except (OSError, ValueError, LookupError, TypeError, yaml.YAMLError):
            continue
    return found


def check(
    directory: Path, manifest: Path | None = None
) -> tuple[str | None, list[str]]:
    """`validate`, and with a manifest also that the set has the manifest's ids and hash."""
    set_hash, errors = validate(directory)
    if manifest and not errors:
        try:
            want = yaml.safe_load(Path(manifest).read_text())
            ids = sorted(c.id for c in load_cases(directory))
            if ids != sorted(want["ids"]) or set_hash != want["sha256"]:
                errors.append(f"{directory} does not match {manifest}")
        except (OSError, yaml.YAMLError, KeyError, TypeError) as e:
            errors.append(f"{manifest}: not a manifest ({type(e).__name__}: {e})")
    return set_hash, errors


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Validate a golden set and print its hash.")
    p.add_argument("command", choices=["validate"])
    p.add_argument("directory", type=Path)
    p.add_argument("--manifest", type=Path, help="fail unless ids and hash match it")
    args = p.parse_args(argv)
    set_hash, errors = check(args.directory, args.manifest)
    for error in errors:
        print(error, file=sys.stderr)
    if errors:
        sys.exit(1)
    print(f"{len(case_files(args.directory))} cases, sha256 {set_hash}")


if __name__ == "__main__":
    main()
