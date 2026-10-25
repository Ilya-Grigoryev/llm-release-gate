import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize("path", ["action.yml", "setup/action.yml"])
def test_actions_use_only_declared_inputs(path):
    text = (ROOT / path).read_text()
    action = yaml.safe_load(text)
    assert action["runs"]["using"] == "composite"
    used = set(re.findall(r"inputs\.([\w-]+)", text))
    assert used and used <= set(action["inputs"])
    assert all("shell" in s or "uses" in s for s in action["runs"]["steps"])


def test_the_gate_action_runs_the_packaged_commands():
    text = (ROOT / "action.yml").read_text()
    for module in (
        "comment --check",
        "golden validate",
        "pr FETCH_HEAD",
        'comment "$OUT/comment.md"',
    ):
        assert f"llm_release_gate.{module}" in text


def _step(name):
    action = yaml.safe_load((ROOT / "action.yml").read_text())
    return next(s for s in action["runs"]["steps"] if s.get("name") == name)


@pytest.mark.parametrize("url", ["", "https://example.com/files/{name}"])
def test_the_cases_step_keeps_text_and_says_where_the_rest_is(tmp_path, url):
    for f in ("a.yaml", "inputs/a.txt", "inputs/a.jpg"):
        (tmp_path / "cases" / f).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "cases" / f).write_text("x")
    env = {"INPUTS_URL": url, "OUT": str(tmp_path), "PATH": "/usr/bin:/bin"}
    subprocess.run(["bash", "-c", _step("cases")["run"]], env=env, check=True)
    cases = tmp_path / "cases"
    left = {str(p.relative_to(cases)) for p in cases.rglob("*") if p.is_file()}
    assert left == {"a.yaml", "inputs/a.txt"} | ({"inputs-url.txt"} if url else set())
    if url:
        assert (cases / "inputs-url.txt").read_text() == url + "\n"
