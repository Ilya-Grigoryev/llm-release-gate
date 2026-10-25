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
def test_the_cases_step_says_where_the_other_files_are(tmp_path, url):
    (tmp_path / "cases").mkdir()
    env = {"INPUTS_URL": url, "OUT": str(tmp_path), "PATH": "/usr/bin:/bin"}
    subprocess.run(["bash", "-c", _step("cases")["run"]], env=env, check=True)
    written = tmp_path / "cases" / "inputs-url.txt"
    assert written.exists() == bool(url)
    if url:
        assert written.read_text() == url + "\n"
