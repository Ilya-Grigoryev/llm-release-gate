import json
import re
import shutil
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


@pytest.mark.skipif(
    shutil.which("jq") is None, reason="needs jq, as GitHub's runners have"
)
@pytest.mark.parametrize(
    "event, fork",
    [
        (
            {
                "pull_request": {"head": {"repo": {"full_name": "me/app"}}},
                "repository": {"full_name": "me/app"},
            },
            "false",
        ),
        (
            {
                "pull_request": {"head": {"repo": {"full_name": "you/app"}}},
                "repository": {"full_name": "me/app"},
            },
            "true",
        ),
        (
            {
                "pull_request": {"head": {"repo": None}},
                "repository": {"full_name": "me/app"},
            },
            "true",
        ),  # a deleted fork
        ({"repository": {"full_name": "me/app"}}, "false"),  # a push
    ],
)
def test_a_pull_request_from_a_fork_is_found(tmp_path, event, fork):
    (tmp_path / "event.json").write_text(json.dumps(event))
    env = {
        "PATH": f"{Path(shutil.which('jq')).parent}:/usr/bin:/bin",
        "GITHUB_EVENT_PATH": str(tmp_path / "event.json"),
    }
    env["GITHUB_OUTPUT"] = str(tmp_path / "output")
    subprocess.run(["bash", "-c", _step("fork")["run"]], env=env, check=True)
    assert (tmp_path / "output").read_text() == f"fork={fork}\n"


def test_a_fork_fails_the_job_and_says_why(tmp_path):
    action = yaml.safe_load((ROOT / "action.yml").read_text())
    steps = action["runs"]["steps"]
    assert all(
        "steps.fork.outputs.fork != 'true'" in s["if"]
        for s in steps
        if s.get("name") in ("pipeline", "can comment", "gate", "comment")
    )
    env = {"PATH": "/usr/bin:/bin", "GITHUB_STEP_SUMMARY": str(tmp_path / "summary")}
    done = subprocess.run(
        ["bash", "-c", _step("not checked")["run"]],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert (
        done.returncode == 1
        and "::error title=Release gate: not checked::" in done.stdout
    )
    assert "comes from a fork" in (tmp_path / "summary").read_text()
