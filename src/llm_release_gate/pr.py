"""Gate a pull or merge request.

For each pipeline in the project's gate.yaml whose version the request changes, run the target branch's version and this
checkout's on the pipeline's test set, each in its own tree and environment, and compare them. OUT/NAME gets the comment,
the verdict, both arms' runs and logs, and cases/ with the set's text files (never images) for whoever reads the results.
Exits with the worst outcome: 20 infra error, 10 quality fail, 12 budget fail, 11 inconclusive, 0 pass.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from llm_release_gate import project
from llm_release_gate.gate import (
    BUDGET_FAIL,
    INCONCLUSIVE,
    INFRA_ERROR,
    PASS,
    QUALITY_FAIL,
)
from llm_release_gate.golden import check

SYNC = [
    "uv",
    "sync",
    "--locked",
    "--quiet",
]  # each tree gets its own environment, its own gate included
PYTHON = ["uv", "run", "--quiet", "python"]
HASH = (
    "import sys; from llm_release_gate.pipeline import config_hash, load_config; "
    "print(config_hash(load_config(sys.argv[1])))"
)
WORST = (INFRA_ERROR, QUALITY_FAIL, BUDGET_FAIL, INCONCLUSIVE, PASS)
TEXT = {".yaml", ".yml", ".json", ".txt", ".md", ".csv"}
ENV = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
BUDGETS = {
    "cost_per_run_usd": "--max-cost-per-run",
    "latency_s": "--max-latency",
    "latency_quantile": "--latency-quantile",
}


class Infra(Exception):
    """The pipeline cannot be decided; the tail of `log` goes into the comment."""

    def __init__(self, message: str, log: Path | None = None):
        super().__init__(message)
        self.log = log


def call(command: list[str], cwd: Path, log: Path) -> int:
    with log.open("a") as f:
        try:
            return subprocess.run(
                command,
                cwd=cwd,
                env=ENV,
                stdout=f,
                stderr=subprocess.STDOUT,
                check=False,
            ).returncode
        except OSError as e:  # the program or the directory is missing
            f.write(f"{command[0]}: {e}\n")
            return 127


def both(first, second):
    with ThreadPoolExecutor(2) as pool:
        a, b = pool.submit(first), pool.submit(second)
        return a.result(), b.result()


def ready(tree: Path, prepare: tuple[str, ...] | None, log: Path) -> bool:
    """Run the project's `prepare`, then sync its environment."""
    return all(call(list(c), tree, log) == 0 for c in (prepare, SYNC) if c)


def version(tree: Path, config: str, log: Path) -> str | None:
    """The config's hash, computed by the tree's own gate; None if it cannot say (the reason goes to `log`)."""
    done = subprocess.run(
        [*PYTHON, "-c", HASH, config],
        cwd=tree,
        env=ENV,
        capture_output=True,
        text=True,
        check=False,
    )
    with log.open("a") as f:
        f.write(done.stderr)
    lines = done.stdout.split()
    return lines[-1] if done.returncode == 0 and lines else None


def copy_text_files(golden: Path, dest: Path) -> None:
    """The set's text files, links followed and copied as files, so nothing else of the set comes along."""
    for directory, dirs, files in os.walk(golden, followlinks=True):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in files:
            source = Path(directory) / name
            if (
                name.startswith(".")
                or source.suffix.lower() not in TEXT
                or not source.is_file()
            ):
                continue  # a hidden file, not text, or a broken link
            target = dest / source.relative_to(golden)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)


def write_comment(
    dest: Path, title: str, message: str, log: Path | None = None
) -> None:
    text = f"**Release gate: {title}**\n\n{message}\n"
    if log and log.is_file():
        tail = log.read_text(errors="replace").splitlines()[-15:]
        text += "\n```\n" + "\n".join(tail) + "\n```\n"
    (dest / "comment.md").write_text(text)


def checked_set(p: project.Pipeline, candidate: Path, dest: Path) -> tuple[Path, str]:
    """The pipeline's set and its hash; its text files go to DEST/cases first, so a reader sees the cases whatever
    happens next."""
    golden = candidate / p.golden
    if not golden.is_dir():
        raise Infra(f"There is no golden set at {p.golden}.")
    copy_text_files(golden, dest / "cases")
    if p.inputs_url:
        (dest / "cases").mkdir(exist_ok=True)
        (dest / "cases" / "inputs-url.txt").write_text(p.inputs_url + "\n")
    set_hash, errors = check(golden, candidate / p.manifest if p.manifest else None)
    if errors:
        raise Infra("The golden set is not valid: " + "; ".join(errors[:5]))
    return golden, set_hash


def unchanged(p: project.Pipeline, config_hash: str, set_hash: str, dest: Path) -> int:
    (dest / "verdict.json").write_text(
        json.dumps(
            {
                "outcome": "unchanged",
                "exit_code": PASS,
                "base_mean": None,
                "candidate_mean": None,
                "diff_pp": None,
                "base_config": config_hash,
                "candidate_config": config_hash,
                "set_hash": set_hash,
            }
        )
        + "\n"
    )
    write_comment(
        dest,
        "⏭ unchanged",
        f"This request does not change `{p.name}`: its config, prompts and pipeline `VERSION` hash the same in both "
        f"branches (`{config_hash[:12]}`), so nothing ran. A code change that changes what the model gets needs a new "
        "`VERSION` in the adapter, or a new number in `params` for `pipeline: command`.",
    )
    return PASS


def one(
    p: project.Pipeline,
    golden: Path,
    set_hash: str,
    candidate: Path,
    base: Path,
    dest: Path,
) -> int:
    if not (candidate / p.config).is_file():
        raise Infra(f"There is no {p.config}.")
    if not (base / p.config).is_file():
        raise Infra(
            f"The target branch has no {p.config}, so there is no base version to compare with."
        )
    logs = dest / "base.log", dest / "candidate.log"
    hashes = both(
        lambda: version(base, p.config, logs[0]),
        lambda: version(candidate, p.config, logs[1]),
    )
    if hashes[0] and hashes[0] == hashes[1]:
        return unchanged(p, hashes[0], set_hash, dest)
    runs = [
        *PYTHON,
        "-m",
        "llm_release_gate.runner",
        "--config",
        p.config,
        "--golden",
        str(golden),
        "-k",
        str(p.k),
    ]
    codes = both(
        lambda: call([*runs, "--out", str(dest / "base.jsonl")], base, logs[0]),
        lambda: call(
            [*runs, "--out", str(dest / "candidate.jsonl")], candidate, logs[1]
        ),
    )
    for arm, code, log in zip(("base version", "candidate"), codes, logs, strict=True):
        if code != 0:
            raise Infra(f"The {arm} did not finish its runs.", log)
    decide = [
        *PYTHON, "-m", "llm_release_gate.gate",
        "--base", str(dest / "base.jsonl"), "--candidate", str(dest / "candidate.jsonl"), "--golden", str(golden),
        "--threshold", str(p.delta), "--markdown", str(dest / "comment.md"), "--json", str(dest / "verdict.json"),
        *(["--prices", p.prices] if p.prices else []),
        *(a for k, flag in BUDGETS.items() if k in p.budgets for a in (flag, str(p.budgets[k]))),
    ]  # fmt: skip
    code = call(decide, candidate, dest / "gate.log")
    if code not in WORST or code == INFRA_ERROR or not (dest / "comment.md").is_file():
        raise Infra("The gate could not compare the runs.", dest / "gate.log")
    return code


def show(dest: Path) -> None:
    """The pipeline's logs and comment, for the CI job's log."""
    for name in (
        ".prepare-base.log",
        ".prepare-candidate.log",
        "base.log",
        "candidate.log",
        "gate.log",
        "comment.md",
    ):
        if (dest / name).is_file():
            print(
                f"--- {dest.name}: {name}\n{(dest / name).read_text(errors='replace')}",
                end="\n",
            )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="llm-release-gate pr", description=__doc__.split("\n\n")[0]
    )
    p.add_argument("--base", help="the target branch's revision, e.g. origin/main")
    p.add_argument(
        "--project",
        type=Path,
        default=Path("."),
        help="the project's directory, with gate.yaml (default .)",
    )
    p.add_argument("--out", type=Path, help="where each pipeline's results go")
    p.add_argument("--pipeline", help="run only this pipeline of gate.yaml")
    p.add_argument(
        "--list", action="store_true", help="check gate.yaml and print its pipelines"
    )
    args = p.parse_args(argv)
    try:
        settings = project.load(args.project)
    except ValueError as e:
        print(f"infra error: {e}", file=sys.stderr)
        return INFRA_ERROR
    if args.list:
        print("\n".join(settings.pipelines))
        return PASS
    if not (args.base and args.out):
        p.error("give --base and --out")
    if args.pipeline not in (None, *settings.pipelines):
        p.error(f"gate.yaml has no pipeline {args.pipeline!r}")
    candidate, out = args.project.resolve(), args.out.resolve()
    top = subprocess.run(
        ["git", "-C", str(candidate), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if top.returncode:
        p.error(f"{args.project} is not in a git repository")
    root = Path(top.stdout.strip()).resolve()
    names = [args.pipeline] if args.pipeline else list(settings.pipelines)
    for name in names:
        shutil.rmtree(out / name, ignore_errors=True)
        (out / name).mkdir(parents=True)
    tree = out / ".base-tree"
    base = tree / candidate.relative_to(root)
    logs = (
        out / ".prepare-base.log",
        out / ".prepare-candidate.log",
    )  # names no pipeline can have
    for log in logs:
        log.unlink(missing_ok=True)
    codes = {}
    try:
        shutil.rmtree(tree, ignore_errors=True)  # left by a run that was killed
        subprocess.run(
            ["git", "worktree", "prune"], cwd=root, capture_output=True, check=False
        )
        problem = None
        if subprocess.run(
            ["git", "worktree", "add", "--detach", str(tree), args.base],
            cwd=root,
            capture_output=True,
            check=False,
        ).returncode:
            problem = Infra(f"Cannot check out the target branch ({args.base}).")
        elif not base.is_dir():
            problem = Infra(
                f"The target branch has no {candidate.relative_to(root)}, so there is no base version to compare with."
            )
        else:
            done = both(
                lambda: ready(base, settings.prepare, logs[0]),
                lambda: ready(candidate, settings.prepare, logs[1]),
            )
            for arm, ok, log in zip(
                ("target branch", "request"), done, logs, strict=True
            ):
                if not ok and not problem:
                    problem = Infra(f"The {arm}'s project could not be prepared.", log)
        for name in names:
            dest = out / name
            for log in logs:
                if log.is_file():
                    shutil.copyfile(log, dest / log.name)
            try:
                golden, set_hash = checked_set(
                    settings.pipelines[name], candidate, dest
                )
                if problem:
                    raise problem
                codes[name] = one(
                    settings.pipelines[name], golden, set_hash, candidate, base, dest
                )
            except Infra as e:
                write_comment(
                    dest, "⚠️ infra error", str(e), e.log and dest / e.log.name
                )
                codes[name] = INFRA_ERROR
            except Exception as e:  # noqa: BLE001 - a bug in one pipeline is an infra error, never a verdict
                traceback.print_exc()
                write_comment(
                    dest, "⚠️ infra error", f"The gate failed: {type(e).__name__}: {e}"
                )
                codes[name] = INFRA_ERROR
            show(dest)
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(tree)],
            cwd=root,
            capture_output=True,
            check=False,
        )
    return min(codes.values(), key=WORST.index)


if __name__ == "__main__":
    sys.exit(main())
