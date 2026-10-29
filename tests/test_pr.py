import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from llm_release_gate import pr

FIXTURES = Path(__file__).parent / "fixtures"
AGENT = FIXTURES / "command" / "agent.sh"
GATE = "pipelines:\n  demo: {config: demo.yaml, golden: golden}\n"


def git(repo, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def version(repo, mode, gate=GATE):
    (repo / "demo.yaml").write_text(
        f"pipeline: command\ncommand: [sh, {AGENT}]\nmodel: fake-model-2026-01-01\n"
        f"prompt: prompt.md\ninput: text\nparams: {{mode: {mode}}}\n"
    )
    (repo / "gate.yaml").write_text(gate)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A project whose target branch answers every case right; the gate runs in this interpreter, without uv."""
    monkeypatch.setattr(pr, "SYNC", None)
    monkeypatch.setattr(pr, "PYTHON", [sys.executable])
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copytree(FIXTURES / "golden", repo / "golden")
    shutil.copy(FIXTURES / "prompt.md", repo / "prompt.md")
    version(repo, "answer")
    git(repo, "init", "-q")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    monkeypatch.chdir(repo)
    return repo


def gate(repo, *args):
    out = repo.parent / "out"
    return pr.main(["--base", "HEAD", "--out", str(out), *args]), out / "demo"


def test_a_worse_version_is_blocked_and_the_results_are_kept(repo):
    version(repo, "bare")  # answers only the total
    code, out = gate(repo)
    assert code == pr.QUALITY_FAIL
    verdict = json.loads((out / "verdict.json").read_text())
    assert (
        verdict["outcome"] == "quality fail"
        and verdict["base_config"] != verdict["candidate_config"]
    )
    assert "quality fail" in (out / "comment.md").read_text()
    assert {p.name for p in out.glob("*.jsonl")} == {"base.jsonl", "candidate.jsonl"}
    assert (out / "cases" / "synth-001.yaml").is_file()
    assert not (repo.parent / "out" / ".base-tree").exists()


def test_settings_reach_the_runs_and_the_gate(repo):
    (repo / "prices.yaml").write_text("fake-model-2026-01-01: [1, 1]\n")
    gate_yaml = (
        GATE + "k: 2\nprices: prices.yaml\nbudgets: {cost_per_run_usd: 0.000001}\n"
    )
    (repo / "gate.yaml").write_text(gate_yaml)  # the rules come from the target branch
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "rules")
    version(repo, "answer-again", gate_yaml)  # the same answers from another version
    code, out = gate(repo)
    assert code == pr.BUDGET_FAIL
    assert len((out / "base.jsonl").read_text().splitlines()) == 2
    assert json.loads((out / "verdict.json").read_text())["budget"] is not None


def test_an_unchanged_version_is_not_run(repo):
    (repo / "README.md").write_text("docs only\n")
    code, out = gate(repo)
    assert code == pr.PASS
    assert json.loads((out / "verdict.json").read_text())["outcome"] == "unchanged"
    assert "unchanged" in (out / "comment.md").read_text()
    assert not list(out.glob("*.jsonl"))


def test_prepare_runs_in_both_trees(repo):
    log = repo.parent / "prepared"
    version(repo, "bare", GATE + f"prepare: [sh, -c, 'pwd >> {log}']\n")
    gate(repo)
    assert len(log.read_text().splitlines()) == 2


def test_a_failed_prepare_is_an_infra_error(repo):
    version(repo, "bare", GATE + "prepare: [sh, -c, 'echo no network; exit 1']\n")
    code, out = gate(repo)
    assert code == pr.INFRA_ERROR
    comment = (out / "comment.md").read_text()
    assert "could not be prepared" in comment and "no network" in comment


def test_without_a_base_version_the_candidate_alone_runs_and_passes(repo):
    version(repo, "answer", GATE + "  new: {config: new.yaml, golden: golden}\n")
    (repo / "new.yaml").write_text((repo / "demo.yaml").read_text())
    code, out = (
        pr.main(
            ["--base", "HEAD", "--out", str(repo.parent / "out"), "--pipeline", "new"]
        ),
        repo.parent / "out" / "new",
    )
    assert code == pr.PASS
    verdict = json.loads((out / "verdict.json").read_text())
    assert verdict["outcome"] == "no base" and verdict["candidate_mean"] == 1.0
    comment = (out / "comment.md").read_text()
    assert "no base version" in comment and "`new` is new in gate.yaml" in comment
    assert [p.name for p in out.glob("*.jsonl")] == ["candidate.jsonl"]


def test_renaming_the_config_keeps_the_base_version(repo):
    (repo / "demo.yaml").rename(repo / "demo2.yaml")
    version(repo, "bare", GATE.replace("demo.yaml", "demo2.yaml"))
    (repo / "demo.yaml").rename(repo / "demo2.yaml")
    assert gate(repo)[0] == pr.QUALITY_FAIL


def test_prepare_cannot_rewrite_the_target_branchs_prices(repo):
    (repo / "prices.yaml").write_text("fake-model-2026-01-01: [1, 1]\n")
    rules = GATE + "prices: prices.yaml\nbudgets: {cost_per_run_usd: 0.000001}\n"
    (repo / "gate.yaml").write_text(rules)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "rules")
    cheap = (
        "prepare: [sh, -c, 'echo \"fake-model-2026-01-01: [0, 0]\" > prices.yaml']\n"
    )
    version(repo, "answer-again", rules + cheap)
    assert gate(repo)[0] == pr.BUDGET_FAIL


def test_a_changed_test_set_is_named(repo):
    case = repo / "golden" / "synth-001.yaml"
    case.write_text(case.read_text().replace("store: TEST MART", "store: OTHER MART"))
    version(repo, "bare")
    _, out = gate(repo)
    assert "changes the test set of `demo`" in (out / "comment.md").read_text()


def test_a_request_that_adds_the_project_runs_the_candidate_alone(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(pr, "SYNC", None)
    monkeypatch.setattr(pr, "PYTHON", [sys.executable])
    repo = tmp_path / "repo"
    (repo / "app").mkdir(parents=True)
    git(repo, "init", "-q")
    git(repo, "commit", "-q", "--allow-empty", "-m", "empty")
    shutil.copytree(FIXTURES / "golden", repo / "app" / "golden")
    shutil.copy(FIXTURES / "prompt.md", repo / "app" / "prompt.md")
    version(repo / "app", "answer")
    monkeypatch.chdir(repo)
    out = tmp_path / "out"
    assert pr.main(["--base", "HEAD", "--project", "app", "--out", str(out)]) == pr.PASS
    assert "no base version" in (out / "demo" / "comment.md").read_text()


def test_the_rules_come_from_the_target_branch(repo):
    version(
        repo, "bare", GATE + "delta: 100\n"
    )  # worse, and a request that loosens its own gate
    code, out = gate(repo)
    assert code == pr.QUALITY_FAIL
    assert json.loads((out / "verdict.json").read_text())["threshold_pp"] == 5
    assert "changes the gate's rules for `demo`" in (out / "comment.md").read_text()


def test_new_prices_in_the_request_wait_for_merge(repo):
    (repo / "prices.yaml").write_text("fake-model-2026-01-01: [1, 1]\n")
    (repo / "gate.yaml").write_text(GATE + "prices: prices.yaml\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "prices")
    (repo / "prices.yaml").write_text("fake-model-2026-01-01: [0, 0]\n")
    version(repo, "answer-again", GATE + "prices: prices.yaml\n")
    code, out = gate(repo)
    assert code == pr.PASS
    assert json.loads((out / "verdict.json").read_text())["cost_usd"]["candidate"] > 0
    assert "changes the gate's rules" in (out / "comment.md").read_text()


def test_without_a_gate_yaml_on_the_target_branch_the_requests_rules_hold(repo):
    (repo / "gate.yaml").unlink()
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "no gate yet")
    version(repo, "bare", GATE + "delta: 100\n")
    code, out = gate(repo)
    assert (
        code == pr.PASS
        and "changes the gate's rules" not in (out / "comment.md").read_text()
    )


def test_a_broken_gate_yaml_on_the_target_branch_is_named(repo):
    (repo / "gate.yaml").write_text("pipelines: [\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "broken")
    version(repo, "bare")
    code, out = gate(repo)
    assert code == pr.QUALITY_FAIL
    assert "target branch's gate.yaml is not valid" in (out / "comment.md").read_text()


def test_a_missing_target_branch_is_an_infra_error_but_the_cases_are_kept(repo):
    code = pr.main(["--base", "no-such-rev", "--out", str(repo.parent / "out")])
    out = repo.parent / "out" / "demo"
    assert code == pr.INFRA_ERROR
    assert "Cannot check out" in (out / "comment.md").read_text()
    assert (out / "cases" / "synth-001.yaml").is_file()


def test_keeps_only_the_sets_text_files(repo):
    golden, elsewhere = repo / "golden", repo.parent / "elsewhere"
    elsewhere.mkdir()
    (golden / "inputs" / "a.TXT").write_text("hello\n")
    (golden / "inputs" / "a.jpg").write_bytes(b"\xff\xd8")
    (golden / ".hidden.yaml").write_text("x")
    (elsewhere / "b.jpg").write_bytes(b"\xff\xd8")
    (elsewhere / "b.json").write_text("{}")
    (golden / "inputs" / "b.json").symlink_to(elsewhere / "b.json")
    (golden / "scans").symlink_to(elsewhere)
    version(repo, "answer", GATE.replace("}", ", inputs-url: 'https://x/{name}'}"))
    _, out = gate(repo)
    files = {
        str(p.relative_to(out / "cases")): p
        for p in (out / "cases").rglob("*")
        if p.is_file()
    }
    assert (
        "inputs/a.TXT" in files and "inputs/b.json" in files and "scans/b.json" in files
    )
    assert not [f for f in files if f.endswith(".jpg") or "hidden" in f]
    assert not any(p.is_symlink() for p in files.values())
    assert files["inputs-url.txt"].read_text() == "https://x/{name}\n"


def test_a_missing_set_is_an_infra_error(repo):
    version(repo, "bare", GATE.replace("golden: golden", "golden: nope"))
    code, out = gate(repo)
    assert code == pr.INFRA_ERROR
    assert "no golden set at nope" in (out / "comment.md").read_text()


def test_list_names_the_pipelines_and_a_bad_gate_yaml_is_an_infra_error(repo, capsys):
    assert pr.main(["--list"]) == pr.PASS
    assert capsys.readouterr().out == "demo\n"
    (repo / "gate.yaml").write_text("pipelines: {demo: {golden: golden}}\n")
    assert pr.main(["--list"]) == pr.INFRA_ERROR
    assert "missing pipelines.demo.config" in capsys.readouterr().err


def test_an_unknown_pipeline_is_refused(repo):
    with pytest.raises(SystemExit):
        pr.main(["--base", "HEAD", "--out", "out", "--pipeline", "nope"])


def test_a_hash_that_cannot_be_computed_runs_both_versions(repo, monkeypatch):
    monkeypatch.setattr(pr, "HASH", "import sys; sys.exit('no hash here')")
    (repo / "README.md").write_text("docs only\n")
    code, out = gate(repo)
    assert code == pr.PASS
    assert {p.name for p in out.glob("*.jsonl")} == {"base.jsonl", "candidate.jsonl"}
    assert "no hash here" in (out / "base.log").read_text()


def test_the_worst_pipeline_decides_and_one_can_be_picked(repo):
    two = GATE + "  same: {config: same.yaml, golden: golden}\n"
    (repo / "same.yaml").write_text((repo / "demo.yaml").read_text())
    (repo / "gate.yaml").write_text(two)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "a second pipeline")
    version(repo, "bare", two)
    code, out = gate(repo)
    assert code == pr.QUALITY_FAIL
    assert "unchanged" in (out.parent / "same" / "comment.md").read_text()
    assert gate(repo, "--pipeline", "same")[0] == pr.PASS


def test_a_broken_link_in_the_set_is_skipped_or_named(repo):
    (repo / "golden" / "inputs" / "gone.txt").symlink_to(repo / "nowhere.txt")
    version(repo, "bare")
    code, out = gate(repo)
    assert (
        code == pr.QUALITY_FAIL and not (out / "cases" / "inputs" / "gone.txt").exists()
    )
    (repo / "golden" / "gone.yaml").symlink_to(
        repo / "nowhere.yaml"
    )  # a case the set cannot read
    code, out = gate(repo)
    assert code == pr.INFRA_ERROR
    assert "gone.yaml: No such file or directory" in (out / "comment.md").read_text()


def test_runs_from_a_subdirectory_of_the_repository(repo, monkeypatch):
    (repo / "sub").mkdir()
    monkeypatch.chdir(repo / "sub")
    version(repo, "bare")
    assert (
        pr.main(["--base", "HEAD", "--project", "..", "--out", "out"])
        == pr.QUALITY_FAIL
    )


def test_a_bug_in_one_pipeline_is_an_infra_error_for_it_alone(repo, monkeypatch):
    def broken(*args):
        raise RuntimeError("boom")

    monkeypatch.setattr(pr, "one", broken)
    code, out = gate(repo)
    assert code == pr.INFRA_ERROR
    assert "RuntimeError: boom" in (out / "comment.md").read_text()


def test_a_rerun_shows_only_its_own_prepare(repo):
    version(repo, "bare", GATE + "prepare: [sh, -c, 'echo PREPARED']\n")
    gate(repo)
    _, out = gate(repo)
    assert (out / ".prepare-candidate.log").read_text().count("PREPARED") == 1


def test_the_project_may_be_given_from_another_directory(
    repo, monkeypatch, tmp_path_factory
):
    monkeypatch.chdir(tmp_path_factory.mktemp("elsewhere"))
    version(repo, "bare")
    assert (
        pr.main(
            [
                "--base",
                "HEAD",
                "--project",
                str(repo),
                "--out",
                str(repo.parent / "out"),
            ]
        )
        == pr.QUALITY_FAIL
    )


def test_a_removed_pipeline_and_changed_rules_are_named_even_on_an_infra_error(repo):
    (repo / "gate.yaml").write_text(
        GATE + "  old: {config: demo.yaml, golden: golden}\n"
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "two pipelines")
    version(
        repo, "bare", GATE.replace("golden: golden", "golden: nope") + "delta: 100\n"
    )
    code, out = gate(repo)
    comment = (out / "comment.md").read_text()
    assert code == pr.INFRA_ERROR and "no golden set at nope" in comment
    assert (
        "changes the gate's rules for `demo`" in comment
        and "removes `old` from gate.yaml" in comment
    )


def test_prices_that_prepare_makes_are_read_after_it(repo):
    make = "prepare: [sh, -c, 'echo \"fake-model-2026-01-01: [1, 1]\" > prices.yaml']\nprices: prices.yaml\n"
    (repo / "gate.yaml").write_text(GATE + make)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "prices made by prepare")
    version(repo, "answer-again", GATE + make)
    code, out = gate(repo)
    assert code == pr.PASS
    assert json.loads((out / "verdict.json").read_text())["cost_usd"]["candidate"] > 0


def test_a_change_to_the_code_alone_runs_both_versions(repo):
    (repo / "src").mkdir()
    (repo / "src" / "agent.py").write_text("print(1)\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "code")
    (repo / "src" / "agent.py").write_text(
        "print(2)\n"
    )  # config and prompts as they were
    code, out = gate(repo)
    assert code == pr.PASS
    assert {p.name for p in out.glob("*.jsonl")} == {"base.jsonl", "candidate.jsonl"}


def test_a_request_that_removes_a_pipeline_fails(repo):
    (repo / "gate.yaml").write_text(
        GATE + "  old: {config: demo.yaml, golden: golden}\n"
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "two pipelines")
    version(repo, "answer")  # gate.yaml without `old`, the rest as it was
    code, out = gate(repo)
    assert code == pr.INCONCLUSIVE  # red, and not a crash of the tool
    assert (
        json.loads((out / "verdict.json").read_text())["outcome"] == "pass"
    )  # demo's own verdict stays true
    assert (
        "removes `old` from gate.yaml: no version of it was compared"
        in (out / "comment.md").read_text()
    )


def test_a_new_ignore_rule_cannot_hide_new_code(repo):
    version(repo, "answer", GATE + "ignore: ['plugins/**']\n")
    (repo / "plugins").mkdir()
    (repo / "plugins" / "evil.py").write_text("print('hidden')\n")
    git(repo, "add", "plugins")
    code, out = gate(repo)
    assert code == pr.PASS and "unchanged" not in (out / "comment.md").read_text()
    assert "changes what the gate ignores" in (out / "comment.md").read_text()


def test_a_changed_test_set_alone_keeps_the_version(repo):
    case = repo / "golden" / "synth-001.yaml"
    case.write_text(case.read_text().replace("store: TEST MART", "store: OTHER MART"))
    _, out = gate(repo)
    comment = (out / "comment.md").read_text()
    assert "unchanged" in comment and "changes the test set of `demo`." in comment
