import ast
from pathlib import Path

import pytest

from llm_release_gate.pipeline import load_config, load_pipeline

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
