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


def run_without_a_base(tmp_path, golden):
    repo, out = tmp_path / "repo", tmp_path / "out"
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
    cases = out / "cases"
    return {str(p.relative_to(cases)): p for p in cases.rglob("*") if not p.is_dir()}


def test_keeps_the_sets_text_files_even_without_a_verdict(tmp_path):
    golden, elsewhere = tmp_path / "golden", tmp_path / "elsewhere"
    (golden / "inputs").mkdir(parents=True)
    elsewhere.mkdir()
    (golden / "a.yaml").write_text("id: a\n")
    (golden / "inputs" / "a.TXT").write_text("hello\n")
    (golden / "inputs" / "a.jpg").write_bytes(b"\xff\xd8")
    (golden / ".hidden.yaml").write_text("x")
    (elsewhere / "b.jpg").write_bytes(b"\xff\xd8")
    (elsewhere / "b.json").write_text("{}")
    (golden / "inputs" / "b.jpg").symlink_to(elsewhere / "b.jpg")
    (golden / "inputs" / "b.json").symlink_to(elsewhere / "b.json")
    (golden / "scans").symlink_to(elsewhere)
    files = run_without_a_base(tmp_path, golden)
    assert sorted(files) == ["a.yaml", "inputs/a.TXT", "inputs/b.json", "scans/b.json"]
    assert not any(p.is_symlink() for p in files.values())
    assert files["inputs/a.TXT"].read_text() == "hello\n"


def test_follows_a_set_that_is_a_link(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (real / "a.yaml").write_text("id: a\n")
    (real / "a.png").write_bytes(b"\x89PNG")
    (tmp_path / "golden").symlink_to(real)
    assert sorted(run_without_a_base(tmp_path, tmp_path / "golden")) == ["a.yaml"]
