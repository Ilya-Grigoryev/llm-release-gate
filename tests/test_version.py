import subprocess
from pathlib import Path

import pytest

from llm_release_gate.version import code_hash, commit, matcher, version_hash

CONFIG = "pipeline: command\ncommand: [sh, agent.sh]\nmodel: m-2026-01-01\nprompt: {p}\ninput: text\n"


def git(repo, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.fixture
def repo(tmp_path):
    """A project with two pipelines, some code, docs, a test set and a web page."""
    repo = tmp_path / "repo"
    write(
        repo / "gate.yaml",
        "ignore: ['web/**']\npipelines:\n  a: {config: a.yaml, golden: golden}\n  b: {config: b.yaml, golden: golden}\n",
    )
    write(repo / "a.yaml", CONFIG.format(p="a.md"))
    write(repo / "b.yaml", CONFIG.format(p="b.md"))
    for name in (
        "a.md",
        "b.md",
        "README.md",
        "docs/guide.txt",
        "golden/c.yaml",
        "web/page.html",
        ".github/ci.yml",
        "src/README.md",
        "src/knowledge.md",
    ):
        write(repo / name, name)
    write(repo / "src" / "agent.py", "print(1)\n")
    git(repo, "init", "-q")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")
    return repo


@pytest.mark.parametrize(
    "path, same",
    [
        ("README.md", True),
        ("src/README.md", True),
        ("src/knowledge.md", False),  # Markdown the code reads
        ("docs/guide.txt", True),
        (".github/ci.yml", True),
        ("web/page.html", True),  # ignored in gate.yaml
        ("golden/c.yaml", True),  # the set has its own hash
        ("b.md", True),  # another pipeline's prompt
        ("b.yaml", True),  # another pipeline's config, another model
        ("src/agent.py", False),  # code, uncommitted
        ("a.md", False),  # this pipeline's prompt
    ],
)
def test_the_version_covers_what_could_change_what_the_model_gets(repo, path, same):
    before = version_hash(repo / "a.yaml")
    edit = (
        CONFIG.format(p="b.md").replace("m-2026", "n-2026")
        if path == "b.yaml"
        else "edited\n"
    )
    (repo / path).write_text(edit)
    assert (version_hash(repo / "a.yaml") == before) is same


def test_a_broken_config_of_another_pipeline_counts_its_files(repo):
    before = version_hash(repo / "a.yaml")
    (repo / "b.yaml").write_text(
        "edited\n"
    )  # its prompts are unknown now, so they count: a runs
    assert version_hash(repo / "a.yaml") != before


def test_untracked_files_do_not_change_the_version(repo):
    before = version_hash(repo / "a.yaml")
    write(repo / "runs" / "a.jsonl", "{}\n")
    write(repo / "src" / "scratch.py", "x = 1\n")
    assert version_hash(repo / "a.yaml") == before


def test_outside_git_the_code_is_unknown(tmp_path):
    write(tmp_path / "a.md", "p")
    config = write(tmp_path / "a.yaml", CONFIG.format(p="a.md"))
    assert code_hash(config) is None and version_hash(config)


def test_commit_marks_uncommitted_edits(repo):
    clean = commit(repo / "a.yaml")
    assert clean and not clean.endswith("+dirty")
    (repo / "src" / "agent.py").write_text("print(2)\n")
    assert commit(repo / "a.yaml") == clean + "+dirty"


@pytest.mark.parametrize(
    "pattern, path, hit",
    [
        ("*.md", "a/b/c.md", True),
        ("*.md", "a/b/c.mdx", False),
        ("docs/**", "docs/x/y.txt", True),
        ("docs/**", "src/docs/y.txt", False),
        ("LICENSE*", "LICENSE.txt", True),
        ("web/*.html", "web/a/b.html", False),
    ],
)
def test_ignore_patterns(pattern, path, hit):
    assert matcher([pattern])(path) is hit
