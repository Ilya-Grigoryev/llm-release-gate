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
    for command in (
        "llm-release-gate pr --project",
        "llm-release-gate comment --check",
        "llm-release-gate pr --base FETCH_HEAD",
        'llm-release-gate comment "$OUT/comment.md"',
    ):
        assert command in text


def _step(name):
    action = yaml.safe_load((ROOT / "action.yml").read_text())
    return next(s for s in action["runs"]["steps"] if s.get("name") == name)


@pytest.mark.parametrize(
    "names, pipeline, ok, name",
    [("demo", "", True, "demo"), ("a\nb", "", False, None), ("a\nb", "b", True, "b")],
)
def test_the_action_finds_the_pipeline(tmp_path, names, pipeline, ok, name):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "uv").write_text(f"#!/bin/sh\nprintf '{names}\\n'\n")
    (bin_dir / "uv").chmod(0o755)
    output = tmp_path / "output"
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "PROJECT": ".",
        "PIPELINE": pipeline,
        "GITHUB_OUTPUT": str(output),
        "RUNNER_TEMP": str(tmp_path),
    }
    done = subprocess.run(
        ["bash", "-c", _step("pipeline")["run"]],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert (done.returncode == 0) == ok
    if ok:
        assert (
            output.read_text()
            == f"name={name}\nout={tmp_path}/llm-release-gate/{name}\n"
        )
    else:
        assert "several pipelines" in done.stdout
