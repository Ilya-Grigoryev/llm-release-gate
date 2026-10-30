import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
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
    monkeypatch.delenv(
        "GITHUB_ACTIONS", raising=False
    )  # no lookups of other jobs' runs
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


def test_another_pipeline_cannot_declare_code_as_its_prompt(repo):
    two = GATE + "  other: {config: other.yaml, golden: golden}\n"
    (repo / "other.yaml").write_text((repo / "demo.yaml").read_text())
    (repo / "gate.yaml").write_text(two)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "two pipelines")
    (repo / "plugins").mkdir()
    (repo / "plugins" / "evil.py").write_text("print('hidden')\n")
    git(repo, "add", "plugins")
    text = (
        (repo / "other.yaml")
        .read_text()
        .replace(
            "prompt: prompt.md", "prompt: {main: prompt.md, extra: plugins/evil.py}"
        )
    )
    (repo / "other.yaml").write_text(text)
    _, out = gate(repo, "--pipeline", "demo")
    assert "unchanged" not in (out / "comment.md").read_text()


# the base from the cache (D-007)


def cached_gate(repo, *args):
    return gate(repo, "--cache", str(repo.parent / "cache"), *args)


def records(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def age(cache, days):
    """Make every cached run DAYS older."""
    for path in cache.glob("*/*.jsonl"):
        lines = []
        for r in records(path):
            t = datetime.fromisoformat(r["timestamp"]) - timedelta(days=days)
            lines.append(json.dumps({**r, "timestamp": t.isoformat()}) + "\n")
        path.write_text("".join(lines))


def test_a_recent_base_comes_from_the_cache(repo):
    version(repo, "bare")
    _, out = cached_gate(repo)
    first = {r["run_id"] for r in records(out / "base.jsonl")}
    assert not any(r.get("reused") for r in records(out / "base.jsonl"))
    assert "reused" not in (out / "comment.md").read_text()
    version(repo, "answer-again")  # another push to the request
    code, out = cached_gate(repo)
    assert code == pr.PASS
    again = records(out / "base.jsonl")
    assert {r["run_id"] for r in again} == first and all(r["reused"] for r in again)
    assert (
        "Base: 1 of 1 runs come from earlier jobs; the oldest ran 0.0 days before"
        in (out / "comment.md").read_text()
    )
    verdict = json.loads((out / "verdict.json").read_text())
    assert verdict["base_reused"]["runs"] == 1
    assert "1 runs of" in (out / "base.log").read_text()


def test_an_old_base_runs_again(repo):
    version(repo, "bare")
    cached_gate(repo)
    age(repo.parent / "cache", 8)  # the default limit is 7 days
    _, out = cached_gate(repo)
    assert not any(r.get("reused") for r in records(out / "base.jsonl"))
    assert "Base:" not in (out / "comment.md").read_text()


def test_the_target_branch_sets_the_age_limit(repo):
    for days, reused in (("0", False), ("10", True)):
        version(repo, "answer", GATE + f"base_max_age_days: {days}\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", f"limit {days}")
        version(repo, "bare", GATE)  # the request's own limit does not count
        shutil.rmtree(repo.parent / "cache", ignore_errors=True)
        cached_gate(repo)
        kept = list((repo.parent / "cache").glob("*/*.jsonl"))
        assert bool(kept) is reused  # 0 keeps nothing
        age(repo.parent / "cache", 8)
        _, out = cached_gate(repo)
        assert any(r.get("reused") for r in records(out / "base.jsonl")) is reused
        assert "changes the gate's rules" in (out / "comment.md").read_text()


def test_a_model_without_a_date_never_comes_from_the_cache(repo):
    for config in (repo / "demo.yaml",):
        config.write_text(
            config.read_text().replace("fake-model-2026-01-01", "fake-model")
        )
    git(repo, "commit", "-q", "-am", "alias")
    version(
        repo, "bare"
    )  # the request asks for a dated model: the base's alias still counts
    cached_gate(repo)
    _, out = cached_gate(repo)
    assert not any(r.get("reused") for r in records(out / "base.jsonl"))
    assert (out / "shared.txt").read_text().split()[
        0
    ] == "candidate"  # the base's alias is never shared


def test_more_runs_per_case_add_to_the_cached_ones(repo):
    version(repo, "bare")
    cached_gate(repo)
    (repo / "gate.yaml").write_text(GATE + "k: 2\n")
    git(repo, "add", "gate.yaml")
    git(repo, "commit", "-q", "-m", "k 2")  # the version stays: gate.yaml is not code
    version(repo, "bare", GATE + "k: 2\n")
    _, out = cached_gate(repo)
    base = records(out / "base.jsonl")
    assert sorted((r["rep"], bool(r.get("reused"))) for r in base) == [
        (0, True),
        (1, False),
    ]


def test_a_new_target_branch_version_is_not_matched_to_old_runs(repo):
    version(repo, "bare")
    cached_gate(repo)
    version(repo, "answer")
    (repo / "prompt.md").write_text((repo / "prompt.md").read_text() + "\nBe brief.\n")
    git(repo, "commit", "-q", "-am", "new prompt on the target branch")
    version(repo, "bare")
    _, out = cached_gate(repo)
    assert not any(r.get("reused") for r in records(out / "base.jsonl"))


def test_reused_runs_are_not_counted_in_the_cost(repo):
    (repo / "prices.yaml").write_text("fake-model-2026-01-01: [1, 1]\n")
    rules = GATE + "prices: prices.yaml\n"
    (repo / "gate.yaml").write_text(rules)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "prices")
    version(repo, "answer-again", rules)
    cached_gate(repo)
    _, out = cached_gate(repo)
    verdict = json.loads((out / "verdict.json").read_text())
    assert verdict["cost_usd"]["base"] == 0 and verdict["cost_usd"]["candidate"] > 0
    assert "without the reused base runs" in (out / "comment.md").read_text()


def test_refresh_fills_the_cache_on_the_target_branch(repo, capsys):
    cache, out = repo.parent / "cache", repo.parent / "refresh"
    assert pr.main(["--refresh", "--cache", str(cache), "--out", str(out)]) == pr.PASS
    assert "demo: 0 runs reused" in capsys.readouterr().out
    assert pr.main(["--refresh", "--cache", str(cache), "--out", str(out)]) == pr.PASS
    assert "demo: 1 runs reused" in capsys.readouterr().out
    version(repo, "bare")
    _, dest = cached_gate(repo)
    assert all(r["reused"] for r in records(dest / "base.jsonl"))


def test_refresh_needs_a_cache(repo):
    with pytest.raises(SystemExit):
        pr.main(["--refresh", "--out", str(repo.parent / "out")])


def record(case, rep, when, run_id="R1", **more):
    """A runner's record; one run id covers a whole runner call."""
    return {"config_hash": "v", "set_hash": "s", "case": case, "rep": rep, "run_id": run_id,
            "timestamp": when.isoformat(), "requested_model": "m-2026-01-01", "error": None,
            "trace": {"steps": [], "native": "base.native.jsonl"}, **more}  # fmt: skip


def lines(*items):
    return "".join(json.dumps(i) + "\n" for i in items)


def test_the_cache_keeps_each_runs_raw_responses_and_the_newest_run(tmp_path):
    runs, cache = tmp_path / "base.jsonl", tmp_path / "cache"
    now = datetime.now(UTC)
    runs.write_text(
        lines(
            record("a", 0, now - timedelta(days=2), "R0"),
            record("a", 0, now, reused=True),
            record("b", 0, now),
            record("c", 0, now, error="boom"),
        )
    )
    pr.native(runs).write_text(
        lines(*({"run_id": i, "case": c, "rep": 0, "native": [c + i]} for i, c in (("R0", "a"), ("R1", "a"), ("R1", "b"))))
    )  # fmt: skip
    cache.mkdir()
    (cache / "x-y.jsonl").write_text(lines(record("a", 0, now - timedelta(days=9))))
    pr.keep(cache, runs, 7)
    assert not (cache / "x-y.jsonl").exists()  # nothing recent in it
    kept = records(cache / "v-s.jsonl")
    assert [(r["case"], r["run_id"]) for r in kept] == [("a", "R1"), ("b", "R1")]
    assert not any("reused" in r for r in kept)
    assert [r["native"] for r in records(pr.native(cache / "v-s.jsonl"))] == [
        ["aR1"],
        ["bR1"],
    ]
    out = tmp_path / "next" / "candidate.jsonl"
    out.parent.mkdir()
    assert pr.reuse(cache, "v", "s", 7, 1, out) == 2
    assert all(
        r["reused"] and r["trace"]["native"] == "candidate.native.jsonl"
        for r in records(out)
    )
    assert [r["native"] for r in records(pr.native(out))] == [["aR1"], ["bR1"]]


def test_the_cache_gives_only_good_recent_runs_of_a_dated_model(tmp_path):
    now, cache = datetime.now(UTC), tmp_path
    (cache / "v-s.jsonl").write_text(
        lines(
            record("a", 0, now),
            record("a", 1, now),  # beyond k
            record("b", 0, now + timedelta(hours=2)),  # a wrong clock
            record("c", 0, now, trace=[1]),  # malformed
            record("e", -1, now),
            {"case": "d"},
        )
    )
    out = tmp_path / "out.jsonl"
    assert pr.reuse(cache, "v", "s", 7, 1, out) == 1
    assert [(r["case"], r["rep"]) for r in records(out)] == [("a", 0)]
    (cache / "w-s.jsonl").write_text(
        lines(record("a", 0, now, config_hash="w", requested_model="m"))
    )
    assert pr.reuse(cache, "w", "s", 7, 1, tmp_path / "none.jsonl") == 0


def commit_rules(repo, rules):
    version(repo, "answer", rules)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "rules")


def test_fewer_runs_per_case_take_only_the_first_cached_ones(repo):
    commit_rules(repo, GATE + "k: 3\n")
    version(repo, "bare", GATE + "k: 3\n")
    cached_gate(repo)
    commit_rules(repo, GATE)
    version(repo, "bare", GATE)
    _, out = cached_gate(repo)
    assert [r["rep"] for r in records(out / "base.jsonl")] == [0]
    assert json.loads((out / "verdict.json").read_text())["runs_per_case"] == {
        "base": 1,
        "candidate": 1,
    }


def test_a_candidate_without_a_dated_model_runs_the_base_too(repo):
    version(repo, "bare")
    cached_gate(repo)
    (repo / "demo.yaml").write_text(
        (repo / "demo.yaml").read_text().replace("fake-model-2026-01-01", "fake-model")
    )
    _, out = cached_gate(repo)
    assert not any(r.get("reused") for r in records(out / "base.jsonl"))


def test_a_changed_test_set_runs_the_base_again(repo):
    version(repo, "bare")
    cached_gate(repo)
    case = repo / "golden" / "synth-001.yaml"
    case.write_text(case.read_text().replace("store: TEST MART", "store: OTHER MART"))
    version(repo, "answer-again")
    _, out = cached_gate(repo)
    assert not any(r.get("reused") for r in records(out / "base.jsonl"))


def test_refresh_says_why_it_keeps_nothing(repo, capsys):
    cache, out = repo.parent / "cache", repo.parent / "refresh"
    for rules, why in (
        (GATE + "base_max_age_days: 0\n", "base_max_age_days is 0"),
        (GATE, "its model has no date"),
    ):
        version(repo, "answer", rules)
        if "0" not in rules:
            (repo / "demo.yaml").write_text(
                (repo / "demo.yaml").read_text().replace("-2026-01-01", "")
            )
        assert (
            pr.main(["--refresh", "--cache", str(cache), "--out", str(out)]) == pr.PASS
        )
        assert f"demo: not cached, {why}" in capsys.readouterr().out
    assert not list(cache.glob("*/*.jsonl"))


def test_the_comment_counts_only_paid_runs_and_says_how_old_the_reused_are(repo):
    (repo / "prices.yaml").write_text("fake-model-2026-01-01: [1, 1]\n")
    commit_rules(repo, GATE + "prices: prices.yaml\n")
    version(repo, "bare", GATE + "prices: prices.yaml\n")
    _, out = cached_gate(repo)
    full = json.loads((out / "verdict.json").read_text())["cost_usd"]["base"]
    age(repo.parent / "cache", 2)
    commit_rules(repo, GATE + "prices: prices.yaml\nk: 2\n")
    version(repo, "bare", GATE + "prices: prices.yaml\nk: 2\n")
    _, out = cached_gate(repo)
    verdict = json.loads((out / "verdict.json").read_text())
    assert (
        0 < verdict["cost_usd"]["base"] == pytest.approx(full)
    )  # one of two runs paid again
    assert verdict["base_reused"]["runs"] == 1 and verdict["base_reused"][
        "days_before_candidate"
    ] == pytest.approx(2, abs=0.01)
    assert (
        "Base: 1 of 2 runs come from earlier jobs; the oldest ran 2.0 days before"
        in (out / "comment.md").read_text()
    )


def test_other_jobs_runs_are_reused_and_this_jobs_are_named_for_upload(
    repo, monkeypatch
):
    version(repo, "bare")
    _, out = cached_gate(repo)
    shared_txt = (out / "shared.txt").read_text().split()
    base, candidate = shared_txt[1], shared_txt[3]
    assert shared_txt[0::2] == ["base", "candidate"] and base != candidate
    assert base.startswith("llm-release-gate-runs-demo-")
    other_job = repo.parent / "artifact" / "base.jsonl"
    other_job.parent.mkdir()
    shutil.copy(out / "base.jsonl", other_job)
    shutil.rmtree(repo.parent / "cache")  # a new job starts without a cache
    asked = []

    def fetch(name, keep, days, env):
        asked.append(name)
        keep(other_job)
        return "earlier runs: found", None

    monkeypatch.setattr(pr.shared, "fetch", fetch)
    version(repo, "answer-again")
    _, out = cached_gate(repo)
    assert asked == [base]
    assert all(r["reused"] for r in records(out / "base.jsonl"))
    assert (out / "shared.txt").read_text().split()[
        0
    ] == "candidate"  # nothing new to share of the base


def test_a_job_that_cannot_read_other_runs_says_so(repo, monkeypatch):
    monkeypatch.setattr(
        pr.shared, "fetch", lambda *a: ("earlier runs: 403", "Give it `actions: read`.")
    )
    version(repo, "bare")
    _, out = cached_gate(repo)
    assert "Give it `actions: read`." in (out / "comment.md").read_text()
    assert "earlier runs: 403" in (out / "base.log").read_text()


def test_refresh_fails_when_it_cannot_run_or_hash(repo, monkeypatch):
    args = [
        "--refresh",
        "--cache",
        str(repo.parent / "cache"),
        "--out",
        str(repo.parent / "refresh"),
    ]
    version(repo, "fail")
    assert pr.main(args) == pr.INFRA_ERROR
    version(repo, "answer")
    monkeypatch.setattr(pr, "version", lambda *a: None)
    assert pr.main(args) == pr.INFRA_ERROR
    monkeypatch.setattr(pr, "checked_set", lambda *a: 1 / 0)
    assert pr.main(args) == pr.INFRA_ERROR


def test_a_broken_cache_never_fails_the_check(repo):
    version(repo, "bare")
    _, out = cached_gate(repo)
    verdict = json.loads((out / "verdict.json").read_text())
    path = (
        repo.parent
        / "cache"
        / "demo"
        / f"{verdict['base_config']}-{verdict['set_hash']}.jsonl"
    )
    [r] = records(path)
    path.write_text(
        json.dumps({**r, "run_id": ["unhashable"], "requested_model": 5}) + "\n"
    )
    code, out = cached_gate(repo)
    assert code == pr.QUALITY_FAIL
    assert not any(r.get("reused") for r in records(out / "base.jsonl"))
    assert "earlier runs: TypeError" in (out / "base.log").read_text()


def test_a_run_from_a_wrong_clock_gives_way_to_a_new_one(tmp_path):
    now = datetime.now(UTC)
    (tmp_path / "v-s.jsonl").write_text(
        lines(record("a", 0, now + timedelta(days=3), "FUTURE"))
    )
    runs = tmp_path / "job" / "base.jsonl"
    runs.parent.mkdir()
    runs.write_text(lines(record("a", 0, now)))
    pr.keep(tmp_path, runs, 7)
    assert [r["run_id"] for r in records(tmp_path / "v-s.jsonl")] == ["R1"]
