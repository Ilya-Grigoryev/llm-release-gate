import ast
from pathlib import Path

import pytest

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
            "pipeline: sroie\nmodel: gpt-4.1-mini-2025-04-14\nprompt: prompt.md\n"
            "input: text\nparams: {temperature: 0, seed: 0}\n",
        )
    )
    assert config.prompt == tmp_path / "prompt.md"
    assert config.params == {"temperature": 0, "seed": 0}


@pytest.mark.parametrize(
    "body",
    [
        "pipeline: sroie\nmodel: gpt-4.1-mini\nprompt: p.md\ninput: text\n",  # alias
        "pipeline: sroie\nmodel: gpt-4.1-mini-2025-04-14\nprompt: p.md\n",  # no input
        (
            "pipeline: sroie\nmodel: gpt-4.1-mini-2025-04-14\nprompt: p.md\ninput: text\n"
            "temprature: 0\n"
        ),  # typo
    ],
)
def test_load_config_rejects_bad_files(tmp_path, body):
    with pytest.raises(ValueError):
        load_config(write(tmp_path / "c.yaml", body))


@pytest.mark.parametrize("name", ["sroie-text.yaml", "sroie-image.yaml"])
def test_shipped_configs_build(name):
    pipeline = load_pipeline(load_config(REPO / "configs" / name), client=object())
    assert pipeline.config.input in name


def test_load_config_accepts_both_snapshot_date_formats(tmp_path):
    for model in ("gpt-4.1-mini-2025-04-14", "claude-sonnet-4-5-20250929"):
        body = f"pipeline: sroie\nmodel: {model}\nprompt: p.md\ninput: text\n"
        assert load_config(write(tmp_path / "c.yaml", body)).model == model


def imported_modules(path: Path) -> set[str]:
    modules = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            modules |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            modules.add("." * node.level + (node.module or ""))
    return modules


def test_gate_code_does_not_import_pipelines():
    outside = [p for p in SRC.rglob("*.py") if "pipelines" not in p.parts]
    assert outside
    for path in outside:
        assert not [m for m in imported_modules(path) if "pipelines" in m], path


CONFIG = (
    "pipeline: sroie\nmodel: gpt-4.1-mini-2025-04-14\nprompt: prompt.md\ninput: text\n"
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
        "prompt: 'prompt.md'\nmodel: \"gpt-4.1-mini-2025-04-14\"\npipeline: sroie\n"
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
    from llm_release_gate.pipelines import sroie

    (tmp_path / "a").mkdir()
    before = config_at(tmp_path / "a")
    monkeypatch.setattr(sroie, "VERSION", sroie.VERSION + 1)
    assert config_at(tmp_path / "a") != before
