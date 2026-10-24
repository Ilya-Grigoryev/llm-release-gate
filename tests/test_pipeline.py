import ast
import re
import sys
from pathlib import Path

import pytest

from llm_release_gate.golden import load_cases
from llm_release_gate.pipeline import (
    config_hash,
    load_config,
    load_pipeline,
    plain_numbers,
)

REPO = Path(__file__).parent.parent
SRC = REPO / "src" / "llm_release_gate"


def write(path: Path, text: str) -> Path:
    path.write_text(text)
    return path


def test_load_config_resolves_prompt_next_to_config(tmp_path):
    (tmp_path / "prompt.md").write_text("Extract fields.")
    config = load_config(
        write(
            tmp_path / "c.yaml",
            "pipeline: replay_pipeline\nmodel: gpt-4.1-mini-2025-04-14\nprompt: prompt.md\n"
            "input: text\nparams: {temperature: 0, seed: 0}\n",
        )
    )
    assert config.prompt == tmp_path / "prompt.md"
    assert config.params == {"temperature": 0, "seed": 0}


@pytest.mark.parametrize(
    "body",
    [
        "pipeline: replay_pipeline\nmodel: gpt-4.1-mini\nprompt: p.md\ninput: text\n",  # alias
        "pipeline: replay_pipeline\nmodel: gpt-4.1-mini-2025-04-14\nprompt: p.md\n",  # no input
        (
            "pipeline: replay_pipeline\nmodel: gpt-4.1-mini-2025-04-14\nprompt: p.md\ninput: text\n"
            "temprature: 0\n"
        ),  # typo
    ],
)
def test_load_config_rejects_bad_files(tmp_path, body):
    with pytest.raises(ValueError):
        load_config(write(tmp_path / "c.yaml", body))


def test_load_config_accepts_both_snapshot_date_formats(tmp_path):
    for model in ("gpt-4.1-mini-2025-04-14", "claude-sonnet-4-5-20250929"):
        body = f"pipeline: replay_pipeline\nmodel: {model}\nprompt: p.md\ninput: text\n"
        assert load_config(write(tmp_path / "c.yaml", body)).model == model


def imported_modules(path: Path) -> set[str]:
    modules = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            modules |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            modules.add("." * node.level + (node.module or ""))
    return modules


def test_gate_code_imports_no_pipeline_and_no_provider():
    """A pipeline reaches the gate only through `pipeline:` in its config."""
    allowed = set(sys.stdlib_module_names) | {"jsonschema", "yaml", "llm_release_gate"}
    for path in SRC.rglob("*.py"):
        absolute = {m.split(".")[0] for m in imported_modules(path) if m[:1] != "."}
        assert absolute <= allowed, (path, absolute - allowed)


CONFIG = (
    "pipeline: replay_pipeline\nmodel: gpt-4.1-mini-2025-04-14\nprompt: prompt.md\ninput: text\n"
    "params: {temperature: 0, seed: 0}\n"
)


def config_at(
    tmp_path: Path, body: str = CONFIG, prompt: str = "Extract fields."
) -> str:
    (tmp_path / "prompt.md").write_text(prompt)
    return config_hash(load_config(write(tmp_path / "c.yaml", body)))


def test_config_hash_ignores_key_order_and_formatting(tmp_path):
    reordered = (
        "# same version, written differently\n"
        "input: text\nparams:\n  seed: 0\n  temperature: 0.0\n"
        "prompt: 'prompt.md'\nmodel: \"gpt-4.1-mini-2025-04-14\"\npipeline: replay_pipeline\n"
    )
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    assert config_at(tmp_path / "a") == config_at(tmp_path / "b", reordered)


@pytest.mark.parametrize(
    "change",
    [
        {"body": CONFIG.replace("temperature: 0", "temperature: 1")},
        {"body": CONFIG.replace("2025-04-14", "2025-04-15")},
        {"body": CONFIG.replace("input: text", "input: image")},
        {"prompt": "Extract fields carefully."},
    ],
)
def test_config_hash_changes_with_the_version(tmp_path, change):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    assert config_at(tmp_path / "a") != config_at(tmp_path / "b", **change)


NAMED = CONFIG.replace(
    "prompt: prompt.md", "prompt: {extract: prompt.md, check: check.md}"
)


def test_named_prompts_resolve_next_to_the_config_and_enter_the_hash(tmp_path):
    (tmp_path / "prompt.md").write_text("Extract fields.")
    (tmp_path / "check.md").write_text("Check fields.")
    config = load_config(write(tmp_path / "c.yaml", NAMED))
    assert config.prompt == {
        "extract": tmp_path / "prompt.md",
        "check": tmp_path / "check.md",
    }
    before = config_hash(config)
    swapped = NAMED.replace(
        "extract: prompt.md, check: check.md", "check: check.md, extract: prompt.md"
    )
    assert config_hash(load_config(write(tmp_path / "d.yaml", swapped))) == before
    (tmp_path / "check.md").write_text("Check the fields.")
    assert config_hash(config) != before


@pytest.mark.parametrize("prompt", ["{}", "[a.md, b.md]", "{check: 1}", "7"])
def test_a_bad_prompt_is_rejected(tmp_path, prompt):
    body = CONFIG.replace("prompt: prompt.md", f"prompt: {prompt}")
    with pytest.raises(ValueError, match="prompt must be"):
        load_config(write(tmp_path / "c.yaml", body))


def test_whole_floats_in_params_become_ints():
    got = plain_numbers({"t": 0.0, "p": 0.5, "n": [1.0, True], "d": {"x": 2.0}})
    assert (
        type(got["t"]) is int
        and type(got["d"]["x"]) is int
        and type(got["n"][0]) is int
    )
    assert got["p"] == 0.5 and got["n"][1] is True
    assert plain_numbers(True) is True


def test_config_hash_changes_with_the_pipeline_code_version(tmp_path, monkeypatch):
    import replay_pipeline

    (tmp_path / "a").mkdir()
    before = config_at(tmp_path / "a")
    monkeypatch.setattr(replay_pipeline, "VERSION", replay_pipeline.VERSION + 1)
    assert config_at(tmp_path / "a") != before


ADAPTER = """
from llm_release_gate.pipeline import Answer

VERSION = 3


class Echo:
    def __init__(self, config):
        self.model = config.model

    def run(self, case):
        return Answer(dict(case.expected), "{}", 1, 1, 0.1, self.model)


def build(config):
    return Echo(config)
"""


def project(tmp_path: Path, monkeypatch, files: dict[str, str]) -> Path:
    """Another project's modules in tmp_path, importable as they would be from its root."""
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text)
    monkeypatch.syspath_prepend(tmp_path)
    (tmp_path / "prompt.md").write_text("Extract fields.")
    return tmp_path


def test_a_module_outside_the_gate_is_named_by_its_import_path(tmp_path, monkeypatch):
    root = project(
        tmp_path,
        monkeypatch,
        {"my_app/__init__.py": "", "my_app/gate_adapter.py": ADAPTER},
    )
    body = CONFIG.replace("replay_pipeline", "my_app.gate_adapter")
    config = load_config(write(root / "c.yaml", body))
    [case] = load_cases(REPO / "tests" / "fixtures" / "golden")
    assert load_pipeline(config).run(case).output == case.expected
    other = load_config(write(root / "d.yaml", CONFIG))
    assert config_hash(config) != config_hash(other)


@pytest.mark.parametrize(
    "name, message",
    [
        ("no_such_app.adapter", "cannot import (ModuleNotFoundError"),
        ("raising_adapter", "cannot import (RuntimeError: no API key)"),
        ("llm_release_gate.hashing", "no build(config) function"),
        ("", "cannot import (ValueError"),
    ],
)
def test_a_bad_pipeline_name_is_a_config_error(tmp_path, monkeypatch, name, message):
    root = project(
        tmp_path,
        monkeypatch,
        {"raising_adapter.py": "raise RuntimeError('no API key')"},
    )
    config = load_config(
        write(root / "c.yaml", CONFIG.replace("replay_pipeline", repr(name)))
    )
    for load in (config_hash, load_pipeline):
        with pytest.raises(ValueError, match=re.escape(message)):
            load(config)
