import ast
import sys
from pathlib import Path

import pytest

from llm_release_gate.pipeline import config_hash, load_config, plain_numbers

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
            "command: [sh, agent.sh]\nmodel: gpt-4.1-mini-2025-04-14\nprompt: prompt.md\n"
            "input: text\nparams: {temperature: 0, seed: 0}\n",
        )
    )
    assert config.prompt == tmp_path / "prompt.md"
    assert config.params == {"temperature": 0, "seed": 0}


@pytest.mark.parametrize(
    "body",
    [
        "command: [sh, agent.sh]\nmodel: ''\nprompt: p.md\ninput: text\n",  # no model
        "command: [sh, agent.sh]\nmodel: gpt-4.1-mini-2025-04-14\nprompt: p.md\n",  # no input
        (
            "command: [sh, agent.sh]\nmodel: gpt-4.1-mini-2025-04-14\nprompt: p.md\ninput: text\n"
            "temprature: 0\n"
        ),  # typo
        "command: [sh, agent.sh]\nmodel: gpt-4.1-mini-2025-04-14\nprompt: p.md\ninput: 5\n",  # input not a name
    ],
)
def test_load_config_rejects_bad_files(tmp_path, body):
    with pytest.raises(ValueError):
        load_config(write(tmp_path / "c.yaml", body))


def test_load_config_accepts_both_snapshot_date_formats(tmp_path):
    for model in ("gpt-4.1-mini-2025-04-14", "claude-sonnet-4-5-20250929"):
        body = f"command: [sh, agent.sh]\nmodel: {model}\nprompt: p.md\ninput: text\n"
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
    """The gate starts the program a config names; it imports no application and no provider's SDK."""
    allowed = set(sys.stdlib_module_names) | {"jsonschema", "yaml", "llm_release_gate"}
    for path in SRC.rglob("*.py"):
        absolute = {m.split(".")[0] for m in imported_modules(path) if m[:1] != "."}
        assert absolute <= allowed, (path, absolute - allowed)


CONFIG = (
    "command: [sh, agent.sh]\nmodel: gpt-4.1-mini-2025-04-14\nprompt: prompt.md\ninput: text\n"
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
        "prompt: 'prompt.md'\nmodel: \"gpt-4.1-mini-2025-04-14\"\ncommand: [sh, 'agent.sh']\n"
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
        {"body": CONFIG.replace("[sh, agent.sh]", "[sh, agent.sh, --fast]")},
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


def test_load_config_accepts_a_model_without_a_date(tmp_path):
    body = "command: [sh, agent.sh]\nmodel: gpt-6-luna\nprompt: p.md\ninput: text\n"
    assert load_config(write(tmp_path / "c.yaml", body)).model == "gpt-6-luna"
