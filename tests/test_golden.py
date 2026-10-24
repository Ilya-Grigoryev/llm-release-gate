import shutil
from datetime import date
from pathlib import Path

import pytest
import yaml

from llm_release_gate.golden import load_cases, validate
from llm_release_gate.hashing import canonical_hash

FIXTURE = Path(__file__).parent / "fixtures" / "golden"


@pytest.fixture
def golden(tmp_path):
    return Path(shutil.copytree(FIXTURE, tmp_path / "golden"))


def edit(path: Path, change) -> None:
    doc = yaml.safe_load(path.read_text())
    change(doc)
    path.write_text(yaml.safe_dump(doc))


def test_fixture_is_valid():
    set_hash, errors = validate(FIXTURE)
    assert errors == []
    assert len(set_hash) == 64


def test_load_cases_resolves_inputs_next_to_the_case():
    [case] = load_cases(FIXTURE)
    assert case.id == "synth-001"
    assert case.inputs == {
        "text": FIXTURE / "inputs" / "synth-001.txt",
        "image": FIXTURE / "inputs" / "synth-001.jpg",
    }
    assert case.expected["total"] == "12.50"
    assert case.scoring["method"] == "field_match"


def test_reformatting_keeps_the_hash(golden):
    before, _ = validate(golden)
    path = golden / "synth-001.yaml"
    doc = yaml.safe_load(path.read_text())
    path.write_text(yaml.safe_dump(dict(reversed(doc.items())), indent=4) + "\n\n")
    assert validate(golden) == (before, [])


@pytest.mark.parametrize(
    "change",
    [
        lambda g: edit(
            g / "synth-001.yaml", lambda d: d["expected"].update(total="12.60")
        ),
        lambda g: (g / "inputs" / "synth-001.txt").write_text("changed"),
        lambda g: (g / "inputs" / "synth-001.jpg").write_bytes(
            (g / "inputs" / "synth-001.jpg").read_bytes()[:-1] + b"\x00"
        ),
    ],
)
def test_content_changes_change_the_hash(golden, change):
    before, _ = validate(golden)
    change(golden)
    after, errors = validate(golden)
    assert errors == [] and after != before


def duplicate(g):
    shutil.copy(g / "synth-001.yaml", g / "synth-002.yaml")


@pytest.mark.parametrize(
    "break_it, message",
    [
        (duplicate, "also in"),
        (lambda g: (g / "inputs" / "synth-001.jpg").unlink(), "missing input"),
        (
            lambda g: edit(
                g / "synth-001.yaml",
                lambda d: d["input"].update(image="../../outside.jpg"),
            ),
            "outside the set",
        ),
        (
            lambda g: edit(
                g / "synth-001.yaml",
                lambda d: d["expected"].update(date=date(2026, 1, 1)),
            ),
            "non-JSON value",
        ),
        (
            lambda g: (g / "synth-001.yaml").write_bytes(b"id: \xff\xfe"),
            "synth-001.yaml",
        ),
        (lambda g: edit(g / "synth-001.yaml", lambda d: d.pop("expected")), "expected"),
        (
            lambda g: edit(g / "synth-001.yaml", lambda d: d.update(version="1")),
            "integer",
        ),
        (
            lambda g: (g / "synth-001.yaml").write_text("id: [unclosed"),
            "synth-001.yaml",
        ),
        (
            lambda g: edit(
                g / "synth-001.yaml", lambda d: d["scoring"].update(method="judge")
            ),
            "scoring: unknown scoring method 'judge'",
        ),
        (
            lambda g: edit(
                g / "synth-001.yaml",
                lambda d: d["scoring"].update(normalise=["punctuation"]),
            ),
            "scoring: unknown normaliser",
        ),
        (
            lambda g: edit(
                g / "synth-001.yaml",
                lambda d: d["scoring"].update(normalise="casefold"),
            ),
            "scoring: normalise must be a list",
        ),
    ],
)
def test_broken_cases_are_reported(golden, break_it, message):
    break_it(golden)
    set_hash, errors = validate(golden)
    assert set_hash is None
    assert any(message in e for e in errors), errors


def test_empty_directory_is_an_error(tmp_path):
    assert validate(tmp_path) == (None, [f"{tmp_path}: no *.yaml cases"])


def test_canonical_hash_ignores_key_order():
    assert canonical_hash({"a": 1, "b": [1, 2]}) == canonical_hash(
        {"b": [1, 2], "a": 1}
    )
    assert canonical_hash({"a": 1}) != canonical_hash({"a": "1"})


def test_yml_files_count_as_cases(golden):
    shutil.copy(golden / "synth-001.yaml", golden / "copy.yml")
    _, errors = validate(golden)
    assert any("also in" in e for e in errors)
