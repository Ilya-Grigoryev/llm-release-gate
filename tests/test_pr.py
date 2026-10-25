import subprocess

from llm_release_gate import pr


def test_runs_the_packaged_script(monkeypatch):
    calls = []
    monkeypatch.setattr(pr.os, "execvp", lambda file, args: calls.append((file, args)))
    pr.main(["FETCH_HEAD", ".", "a.yaml", "golden", "out"])
    assert pr.SCRIPT.is_file()
    assert calls == [
        ("bash", ["bash", str(pr.SCRIPT), "FETCH_HEAD", ".", "a.yaml", "golden", "out"])
    ]


def test_keeps_the_golden_set_next_to_the_results_even_without_a_verdict(tmp_path):
    repo, golden, out = tmp_path / "repo", tmp_path / "golden", tmp_path / "out"
    (golden / "inputs").mkdir(parents=True)
    (golden / "a.yaml").write_text("id: a\n")
    (golden / "inputs" / "a.txt").write_text("hello\n")
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    done = subprocess.run(
        ["bash", str(pr.SCRIPT), "no-such-rev", ".", "a.yaml", str(golden), str(out)],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 20
    assert "infra error" in (out / "comment.md").read_text()
    assert (out / "cases" / "a.yaml").read_text() == "id: a\n"
    assert (out / "cases" / "inputs" / "a.txt").read_text() == "hello\n"
