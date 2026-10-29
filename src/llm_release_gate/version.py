"""What a version is (D-025): its config, its prompt files and the code of its repository, the code taken from git.

Two runs are of the same version when the config, the prompts and every tracked file that could change what the model
gets are the same. A file counts by the id git gives its content: an unmodified file by the id in the index, a modified
one by the id of what is on disk, so uncommitted edits count, and Git LFS, line endings and links read alike in every
checkout. Untracked files never count. The whole repository counts (a monorepo's shared code and lock file too), but
documentation, CI, gate.yaml with the price files it names, the paths it ignores, its test sets and the files of its
other pipelines.
"""

import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from llm_release_gate import project
from llm_release_gate.hashing import canonical_hash
from llm_release_gate.pipeline import config_hash, load_config

DOCS = (
    "README*",
    "CHANGELOG*",
    "CONTRIBUTING*",
    "LICENSE*",
)  # at any depth, in any case
DIRS = ("docs/", ".github/")  # at the root of the repository or of the project
GITLINK = "160000"  # a submodule: git keeps its commit, not files


def matcher(
    patterns: list[str] | tuple[str, ...], ignorecase: bool = False
) -> Callable[[str], bool]:
    """Glob patterns over paths with `/`: `*` stays within a directory, `**` crosses them (`**/` may match nothing), a
    trailing `/` takes the whole directory, and a pattern without `/` matches a file name at any depth."""

    def regex(pattern: str) -> re.Pattern:
        pattern += "**" if pattern.endswith("/") else ""
        rx = re.escape(pattern).replace(r"\*\*/", "(.*/)?").replace(r"\*\*", ".*")
        rx = rx.replace(r"\*", "[^/]*").replace(r"\?", "[^/]")
        return re.compile(
            rx if "/" in pattern else "(.*/)?" + rx, re.IGNORECASE if ignorecase else 0
        )

    found = [regex(p) for p in patterns]
    return lambda path: any(r.fullmatch(path) for r in found)


def git(directory: Path, *args: str, stdin: str | None = None) -> str | None:
    done = subprocess.run(
        ["git", "-C", str(directory), *args],
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
    )
    return done.stdout if done.returncode == 0 else None


def root_of(path: Path) -> Path | None:
    top = git(path, "rev-parse", "--show-toplevel")
    return Path(top.strip()).resolve() if top else None


def project_dir(config: Path) -> Path | None:
    """The directory of the nearest gate.yaml above the config, inside its git repository; else the repository's root.
    None outside git."""
    root = root_of(config.parent)
    if root is None:
        return None
    directory = config.resolve().parent
    while not (directory / project.FILE).is_file():
        if directory == root or directory == directory.parent:
            return root
        directory = directory.parent
    return directory


def prompts(config: Path) -> list[Path]:
    """The prompt files a config names; none if it does not load (its own run reports why)."""
    try:
        prompt = load_config(config).prompt
    except (ValueError, OSError):
        return []
    return [prompt] if isinstance(prompt, Path) else list(prompt.values())


def left_out(config: Path, directory: Path) -> tuple[list[str], set[Path]]:
    """gate.yaml's exclusions for this config: the patterns it ignores, and the files and directories that are not this
    pipeline's code (gate.yaml, its price files, the test sets, the other pipelines' configs and prompts)."""
    skip = {directory / project.FILE}
    try:
        settings = (
            project.load(directory) if (directory / project.FILE).is_file() else None
        )
    except (
        ValueError
    ):  # the gate reports a broken gate.yaml itself; the hash still covers the code
        settings = None
    if settings is None:
        return [], {s.resolve() for s in skip}
    for p in settings.pipelines.values():
        skip |= {directory / f for f in (p.golden, p.manifest, p.prices) if f}
        other = directory / p.config
        if other.resolve() != config and other.is_file():
            skip |= {other, *prompts(other)}
    if price := settings.defaults.get("prices"):
        skip.add(directory / price)
    return list(settings.ignore), {s.resolve() for s in skip}


def code_hash(config: Path) -> str | None:
    """The hash of the repository's tracked files that could change what the model gets; None outside git."""
    config = Path(config).resolve()
    root, directory = root_of(config.parent), project_dir(config)
    if root is None or directory is None:
        return None
    patterns, skip = left_out(config, directory)
    docs, dirs, ignored = (
        matcher(DOCS, ignorecase=True),
        matcher(DIRS),
        matcher(patterns),
    )
    inside = "" if directory == root else directory.relative_to(root).as_posix() + "/"

    def counts(name: str) -> bool:
        own = name[len(inside) :] if name.startswith(inside) else None
        if (
            docs(name)
            or dirs(name)
            or (own is not None and (dirs(own) or ignored(own)))
        ):
            return False
        path = (root / name).resolve()
        return not any(s == path or s in path.parents for s in skip)

    gone = set((git(root, "ls-files", "-z", "--deleted") or "").split("\0"))
    ids, modes = {}, {}
    for entry in (git(root, "ls-files", "-z", "--stage") or "").split("\0"):
        if not entry:
            continue
        info, name = entry.split("\t", 1)
        mode, blob, _ = info.split()
        if name not in gone and counts(name):
            ids[name], modes[name] = blob, mode
    edited = [
        n
        for n in (git(root, "ls-files", "-z", "--modified") or "").split("\0")
        if n in ids
    ]
    files = [n for n in edited if modes[n] != GITLINK]
    if files:
        ids.update(
            zip(
                files,
                (
                    git(root, "hash-object", "--stdin-paths", stdin="\n".join(files))
                    or ""
                ).split(),
            )
        )
    for name in (n for n in edited if modes[n] == GITLINK):
        ids[name] = (git(root / name, "rev-parse", "HEAD") or ids[name]).strip()
    return canonical_hash(ids)


def version_hash(config: Path) -> str:
    """The identity of a version: its config with the bytes of its prompts, and the code of its repository."""
    return canonical_hash(
        {"config": config_hash(load_config(config)), "code": code_hash(config)}
    )


def commit(config: Path) -> str | None:
    """The repository's commit, with `+dirty` when tracked files differ from it; for finding a run's code, not for
    comparing."""
    root = root_of(Path(config).resolve().parent)
    head = git(root, "rev-parse", "HEAD") if root else None
    if head is None:
        return None
    dirty = git(root, "status", "--porcelain", "--untracked-files=no")
    return head.strip() + ("+dirty" if dirty else "")
