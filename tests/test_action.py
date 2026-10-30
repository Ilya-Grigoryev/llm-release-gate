import json
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
            == f"name={name}\nout={tmp_path}/llm-release-gate/{name}\ncache={tmp_path}/llm-release-gate-cache\n"
        )
    else:
        assert "several pipelines" in done.stdout


def pr_event(head):
    return {
        "pull_request": {"head": {"repo": head and {"full_name": head}}},
        "repository": {"full_name": "me/app"},
    }


@pytest.mark.parametrize(
    "name, event, fork",
    [
        ("pull_request", pr_event("me/app"), "false"),
        ("pull_request", pr_event("you/app"), "true"),
        ("pull_request", pr_event(None), "true"),  # the fork was deleted
        ("push", {"repository": {"full_name": "me/app"}}, "false"),
        (
            "pull_request_target",
            pr_event("you/app"),
            "false",
        ),  # secrets are there: T-86
    ],
)
def test_a_pull_request_from_a_fork_is_found(tmp_path, name, event, fork):
    (tmp_path / "event.json").write_text(json.dumps(event))
    env = {
        "PATH": "/usr/bin:/bin",
        "GITHUB_EVENT_PATH": str(tmp_path / "event.json"),
        "GITHUB_EVENT_NAME": name,
        "GITHUB_OUTPUT": str(tmp_path / "output"),
    }
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


@pytest.mark.parametrize(
    "base_ref, command",
    [("main", "pr --base FETCH_HEAD"), ("", "pr --refresh")],
)
def test_a_request_is_gated_and_a_push_refreshes_the_cache(tmp_path, base_ref, command):
    bin_dir, log = tmp_path / "bin", tmp_path / "log"
    bin_dir.mkdir()
    for tool in ("uv", "git"):
        (bin_dir / tool).write_text(f'#!/bin/sh\necho "{tool} $*" >> {log}\n')
        (bin_dir / tool).chmod(0o755)
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "PROJECT": ".",
        "NAME": "demo",
        "CACHE": str(tmp_path / "cache"),
        "GITHUB_BASE_REF": base_ref,
        "RUNNER_TEMP": str(tmp_path),
    }
    subprocess.run(["bash", "-c", _step("gate")["run"]], env=env, check=True)
    calls = log.read_text()
    assert f"llm-release-gate {command}" in calls
    assert f"--cache {tmp_path / 'cache'}" in calls
    assert ("git fetch" in calls) is bool(base_ref)


@pytest.mark.parametrize("files, saved", [([], ""), (["v-s.jsonl"], "any=true\n")])
def test_only_a_cache_with_runs_is_saved(tmp_path, files, saved):
    (tmp_path / "cache").mkdir()
    for name in files:
        (tmp_path / "cache" / name).write_text("{}\n")
    output = tmp_path / "output"
    output.write_text("")
    env = {
        "PATH": "/usr/bin:/bin",
        "DIR": str(tmp_path / "cache"),
        "GITHUB_OUTPUT": str(output),
    }
    subprocess.run(["bash", "-c", _step("cached runs")["run"]], env=env, check=True)
    assert output.read_text() == saved
