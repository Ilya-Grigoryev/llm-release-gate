"""What a version is (D-025): its config, its prompt files and the code of its project, the code taken from git.

Two runs are of the same version when the config, the prompts and every project file that could change what the model
gets hash the same. Those files are what git tracks in the project, as they are on disk (uncommitted edits included),
but documentation, CI, gate.yaml, the paths gate.yaml ignores, the test sets and the files of the project's other
pipelines. Untracked files (run records, data) are left out, so writing results never changes the version.
"""

import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from llm_release_gate import project
from llm_release_gate.hashing import canonical_hash, file_hash
from llm_release_gate.pipeline import config_hash, load_config

# documentation and CI; not every *.md: prompts and knowledge files are often Markdown
IGNORED = (
    "README*",
    "CHANGELOG*",
    "CONTRIBUTING*",
    "LICENSE*",
    "docs/**",
    ".github/**",
    project.FILE,
)


def matcher(patterns: list[str]) -> Callable[[str], bool]:
    """Glob patterns over paths with `/`: `*` stays within a directory, `**` crosses them, and a pattern without `/`
    matches a file name at any depth."""

    def regex(pattern: str) -> re.Pattern:
        rx = (
            re.escape(pattern)
            .replace(r"\*\*", ".*")
            .replace(r"\*", "[^/]*")
            .replace(r"\?", "[^/]")
        )
        return re.compile(rx if "/" in pattern else "(.*/)?" + rx)

    found = [regex(p) for p in patterns]
    return lambda path: any(r.fullmatch(path) for r in found)


def git(directory: Path, *args: str) -> str | None:
    done = subprocess.run(
        ["git", "-C", str(directory), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return done.stdout if done.returncode == 0 else None


def project_dir(config: Path) -> Path | None:
    """The directory of the nearest gate.yaml above the config, inside its git repository; else the repository's root.
    None outside git."""
    top = git(config.parent, "rev-parse", "--show-toplevel")
    if top is None:
        return None
    root, directory = Path(top.strip()).resolve(), config.resolve().parent
    while not (directory / project.FILE).is_file():
        if directory == root or directory == directory.parent:
            return root
        directory = directory.parent
    return directory


def code_hash(config: Path) -> str | None:
    """The hash of the project files that could change what the model gets; None outside git."""
    config = Path(config).resolve()
    directory = project_dir(config)
    if directory is None:
        return None
    patterns, skip = list(IGNORED), set()
    if (directory / project.FILE).is_file():
        try:
            settings = project.load(directory)
        except (
            ValueError
        ):  # the gate reports a broken gate.yaml itself; the hash still covers the code
            settings = None
        if settings:
            patterns += settings.ignore
            for p in settings.pipelines.values():
                skip |= {(directory / f).resolve() for f in (p.golden, p.manifest) if f}
                other = directory / p.config
                if other.resolve() != config and other.is_file():
                    skip |= {other.resolve(), *(f.resolve() for f in prompts(other))}
    listed = git(directory, "ls-files", "-z", "--cached") or ""
    ignored, files = matcher(patterns), {}
    for name in sorted(set(listed.split("\0")) - {""}):
        path = directory / name
        real = path.resolve()
        if (
            ignored(name)
            or not path.is_file()
            or any(s == real or s in real.parents for s in skip)
        ):
            continue
        files[name] = file_hash(path)
    return canonical_hash(files)


def prompts(config: Path) -> list[Path]:
    """The prompt files a config names; none if it does not load (its own run reports why)."""
    try:
        prompt = load_config(config).prompt
    except (ValueError, OSError):
        return []
    return [prompt] if isinstance(prompt, Path) else list(prompt.values())


def version_hash(config: Path) -> str:
    """The identity of a version: its config with the bytes of its prompts, and the code of its project."""
    return canonical_hash(
        {"config": config_hash(load_config(config)), "code": code_hash(config)}
    )


def commit(config: Path) -> str | None:
    """The project's commit, with `+dirty` when files differ from it; for finding a run's code, not for comparing."""
    directory = Path(config).resolve().parent
    head = git(directory, "rev-parse", "HEAD")
    if head is None:
        return None
    dirty = git(directory, "status", "--porcelain", "--untracked-files=no", ".")
    return head.strip() + ("+dirty" if dirty else "")
