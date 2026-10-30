import subprocess
from pathlib import Path

import pytest

from llm_release_gate.version import code_hash, commit, matcher, version_hash

CONFIG = "command: [sh, agent.sh]\nmodel: m-2026-01-01\nprompt: {p}\ninput: text\n"


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
        ("web/", "web/a/b.html", True),
        ("**/x.py", "x.py", True),
        ("**/x.py", "a/b/x.py", True),
    ],
)
def test_ignore_patterns(pattern, path, hit):
    assert matcher([pattern])(path) is hit


def test_the_repository_counts_above_the_project_and_a_dirty_commit_is_seen_from_configs(
    tmp_path,
):
    repo = tmp_path / "mono"
    write(repo / "uv.lock", "v1\n")  # a monorepo's shared lock file, above the project
    write(
        repo / "app" / "gate.yaml",
        "pipelines: {a: {config: configs/a.yaml, golden: golden}}\n",
    )
    write(repo / "app" / "configs" / "a.md", "p")
    config = write(repo / "app" / "configs" / "a.yaml", CONFIG.format(p="a.md"))
    write(repo / "app" / "src" / "agent.py", "print(1)\n")
    git(repo, "init", "-q")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")
    before, clean = version_hash(config), commit(config)
    (repo / "uv.lock").write_text("v2\n")
    assert version_hash(config) != before
    assert commit(config) == clean + "+dirty"


def test_the_price_file_is_a_rule_not_code(repo):
    write(repo / "prices.yaml", "m-2026-01-01: [1, 1]\n")
    (repo / "gate.yaml").write_text(
        (repo / "gate.yaml").read_text() + "prices: prices.yaml\n"
    )
    git(repo, "add", "-A")
    before = version_hash(repo / "a.yaml")
    (repo / "prices.yaml").write_text("m-2026-01-01: [2, 2]\n")
    assert version_hash(repo / "a.yaml") == before


def test_documentation_is_found_in_any_case():
    assert matcher(["README*"], ignorecase=True)("src/readme.md")


@pytest.mark.parametrize(
    "name", ["src/changelog.py", "src/license_check.py", "kb/readme_faq.md"]
)
def test_code_named_like_documentation_counts(repo, name):
    write(repo / name, "1\n")
    git(repo, "add", "-A")
    before = version_hash(repo / "a.yaml")
    (repo / name).write_text("2\n")
    assert version_hash(repo / "a.yaml") != before


def test_an_odd_file_name_does_not_hide_other_edits(repo):
    write(repo / '"q".py', "1\n")
    git(repo, "add", "-A")
    before = version_hash(repo / "a.yaml")
    (repo / '"q".py').write_text("2\n")
    (repo / "src" / "agent.py").write_text("print(2)\n")
    after = version_hash(repo / "a.yaml")
    (repo / '"q".py').write_text("1\n")
    assert after != version_hash(repo / "a.yaml") != before


def test_an_edit_git_cannot_read_stops_rather_than_passes_unseen(repo):
    (repo / "src" / "agent.py").write_text("print(2)\n")
    (repo / "src" / "agent.py").chmod(0)
    try:
        with pytest.raises(RuntimeError, match="git cannot read edited files"):
            version_hash(repo / "a.yaml")
    finally:
        (repo / "src" / "agent.py").chmod(0o644)


def test_gate_yaml_may_take_documentation_back_and_anchor_patterns(repo):
    gate = (
        (repo / "gate.yaml")
        .read_text()
        .replace("ignore: ['web/**']", "ignore: ['/web/', '!docs/guide.txt']")
    )
    (repo / "gate.yaml").write_text(gate)
    before = version_hash(repo / "a.yaml")
    (repo / "docs" / "guide.txt").write_text("the assistant answers from this\n")
    assert version_hash(repo / "a.yaml") != before
    before = version_hash(repo / "a.yaml")
    (repo / "web" / "page.html").write_text("new look\n")
    assert version_hash(repo / "a.yaml") == before
