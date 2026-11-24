"""Gate a pull or merge request.

For each pipeline in the project's gate.yaml whose version the request changes, run the target branch's version and this
checkout's on the pipeline's test set, each in its own tree and environment, and compare them. OUT/NAME gets the comment,
the verdict, both arms' runs and logs, and cases/ with the set's text files (never images) for whoever reads the results.
Exits with the worst outcome: 20 infra error, 10 quality fail, 12 budget fail, 11 inconclusive, 13 set changed, 0 pass.

A request that changes the files defining a pipeline's test set (D-035), as the target branch's gate.yaml names them
(the set's tracked files, its manifest), gets `set changed` (13) instead of an exit 0: the versions ran on the
request's cases, so a person reviews the case edits and merges over the check.

With --cache, runs outlive the job (D-007): when `base_max_age_hours` is above 0 (D-033) the gate reuses the target
branch's runs of the same version on the same set, up to that age, from that directory and from other jobs' artifacts
(`shared`), instead of running them again. OUT/NAME/shared.txt names the arms this job paid for, for the CI to upload; --refresh runs the target branch's
version on its own.

With --rounds K both versions run K rounds and the gate decides once, even when the request leaves the version as it
is: a job of unchanged versions measures the noise.

With `max_spend_usd` (D-032) the gate buys rounds, one run of every case by both versions, until it decides or the next
round would not fit; a re-run of the job continues with the rounds paid for and the base runs they were compared with
(OUT/NAME/pinned.jsonl, uploaded with the candidate's runs), with or without a cache of the base.
"""

import argparse
import json
import math
import os
import posixpath
import shutil
import subprocess
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

from llm_release_gate import criterion, project, shared
from llm_release_gate.compare import Mismatch, load_arm
from llm_release_gate.gate import (
    BUDGET_FAIL,
    INCONCLUSIVE,
    INFRA_ERROR,
    PASS,
    QUALITY_FAIL,
    SET_CHANGED,
    complete,
    k_c,
    split,
)
from llm_release_gate.golden import case_hashes, check, load_cases
from llm_release_gate.runner import read_records
from llm_release_gate.version import GITLINK, ids_on_disk, own_files

SYNC = [
    "uv",
    "sync",
    "--locked",
    "--quiet",
]  # each tree gets its own environment, its own gate included
PYTHON = ["uv", "run", "--quiet", "python"]
HASH = "import sys; from llm_release_gate.version import version_hash; print(version_hash(sys.argv[1]))"
WORST = (INFRA_ERROR, QUALITY_FAIL, BUDGET_FAIL, INCONCLUSIVE, SET_CHANGED, PASS)
TEXT = {".yaml", ".yml", ".json", ".txt", ".md", ".csv"}
# the pipelines' code gets no token: only the gate reads other jobs' runs (`shared`)
ENV = {
    k: v
    for k, v in os.environ.items()
    if k not in ("VIRTUAL_ENV", "GITHUB_TOKEN", "GH_TOKEN")
}
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


def native(runs: Path) -> Path:
    """The runner's file of raw provider responses next to RUNS."""
    return runs.with_name(runs.stem + ".native.jsonl")


# run id, case, repetition: one run id covers a whole runner call
Key = tuple[str, str, int]


def key(r: dict) -> Key:
    return r.get("run_id"), r.get("case"), r.get("rep")


def raw_lines(runs: Path) -> dict[Key, str]:
    """Each run's line of raw responses."""
    return {key(r): json.dumps(r) + "\n" for r in read_records(native(runs))}


def when(record: dict) -> datetime | None:
    try:
        t = datetime.fromisoformat(record["timestamp"])
    except (KeyError, TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def recent(record: dict, days: float) -> bool:
    """Run at most DAYS ago; a time ahead of this clock by more than a minute is a wrong clock, never recent."""
    now, t = datetime.now(UTC), when(record)
    return t is not None and now - timedelta(days=days) <= t <= now + timedelta(
        minutes=1
    )


def cached(path: Path, version_hash: str, set_hash: str) -> dict[tuple[str, int], dict]:
    """The error-free runs in PATH of this version on this set, by case and repetition; a malformed line is skipped."""
    return {
        (r["case"], r["rep"]): r
        for r in read_records(path)
        if (r.get("config_hash"), r.get("set_hash")) == (version_hash, set_hash)
        and r.get("error") is None
        and isinstance(r.get("case"), str)
        and type(r.get("rep")) is int
        and r["rep"] >= 0
        and isinstance(r.get("trace") or {}, dict)
        and all(
            isinstance(r.get(f), (str, type(None)))
            for f in ("run_id", "requested_model", "model")
        )
    }


CONTINUE_DAYS = 14  # a re-run of an adaptive job reuses its own rounds this long: the action keeps run artifacts 14 days


def stored(
    cache: Path, version_hash: str, set_hash: str, met: str | None = None
) -> Path:
    """The cache's file of a version's runs on a set; with MET, only the base runs that candidate's rounds met (D-033)."""
    return cache / f"{version_hash}-{set_hash}{f'-met-{met[:16]}' if met else ''}.jsonl"


def reuse(
    cache: Path,
    version_hash: str,
    set_hash: str,
    days: float,
    k: int | None,
    out: Path,
    met: str | None = None,
) -> int:
    """Copy the cache's error-free runs of this version on this set, the first K per case (all if None), at most DAYS
    old, to OUT with their raw responses, each marked `reused`; the runner then runs only the rest. MET: from the file of
    the base runs that candidate met. Returns how many it copied."""
    path = stored(cache, version_hash, set_hash, met)
    have = {
        (r.get("case"), r.get("rep")) for r in read_records(out)
    }  # restored pairs stay
    runs = [
        r
        for at, r in cached(path, version_hash, set_hash).items()
        if (k is None or at[1] < k) and recent(r, days) and at not in have
    ]
    raw, lines, raws = raw_lines(path), [], []
    for r in runs:
        trace = r.get("trace")
        if trace and trace.get("native"):
            if key(r) in raw:
                raws.append(raw[key(r)])
                trace["native"] = native(out).name
            else:
                del trace["native"]
        lines.append(json.dumps({**r, "reused": True}) + "\n")
    # the raw responses first: a record never points to a missing line
    with native(out).open("a") as f:
        f.writelines(raws)
    with out.open("a") as f:
        f.writelines(lines)
    return len(runs)


def keep(
    cache: Path,
    runs: Path,
    days: float,
    met: str | None = None,
    stale: float | None = None,
) -> None:
    """Add RUNS' error-free runs to the cache (MET: to the file of the runs that met version MET, for a re-run), and
    delete files without a run from the last DAYS. Per case and repetition a run already kept stays until it is STALE
    days old (default DAYS; a met file's, CONTINUE_DAYS): a re-run that continues reads the records its first look read
    (D-032); within RUNS the later line wins."""
    stale = CONTINUE_DAYS if met else days if stale is None else stale
    cache.mkdir(parents=True, exist_ok=True)
    for old in cache.glob("*.jsonl"):
        if not old.name.endswith(".native.jsonl") and not any(
            recent(r, days) for r in read_records(old)
        ):
            old.unlink()
            native(old).unlink(missing_ok=True)
    found = read_records(runs)
    raw = raw_lines(runs)
    for version_hash, set_hash in {
        (r.get("config_hash"), r.get("set_hash")) for r in found
    }:
        if not all(
            isinstance(h, str) and h.isalnum() for h in (version_hash, set_hash)
        ):
            continue  # a hash names a file
        path = stored(cache, version_hash, set_hash, met)
        merged, raw_old = cached(path, version_hash, set_hash), raw_lines(path)
        for at, r in cached(runs, version_hash, set_hash).items():
            old = merged.get(at)
            if when(r) and (old is None or not recent(old, stale)):
                merged[at] = {k: v for k, v in r.items() if k != "reused"}
        lines = "".join(json.dumps(r) + "\n" for r in merged.values())
        kept = "".join(
            line
            for r in merged.values()
            if (line := raw.get(key(r)) or raw_old.get(key(r)))
        )
        native(path).write_text(kept)
        path.write_text(lines)


def earlier(
    p: project.Pipeline,
    cache: Path,
    version_hash: str,
    set_hash: str,
    out: Path | None,
    log: Path,
    k: int | None,
    days: float,
    keep_days: float | None = None,
    routes: dict[str, str] | None = None,
) -> tuple[int, str | None]:
    """Put the version's runs at most DAYS old, from CACHE and from other jobs, into OUT (None: only fetch them). The
    cache keeps runs KEEP_DAYS (default DAYS); ROUTES sends a file of the artifact, by name, to the met file of the given
    version (`stored`), which only a re-run of that pair reads. Returns how many runs, and a note for the comment when
    the job cannot read other jobs' runs."""
    keep_days = days if keep_days is None else keep_days
    routes = routes or {}
    try:
        line, note = shared.fetch(
            shared.name(p.name, version_hash, set_hash),
            lambda runs: keep(cache, runs, keep_days, routes.get(runs.name), days),
            days,
            os.environ,
        )
        reused = reuse(cache, version_hash, set_hash, days, k, out) if out else 0
    except Exception as e:  # noqa: BLE001 - reuse saves money and must never fail a check: the base runs
        line, note, reused = f"earlier runs: {type(e).__name__}: {e}", None, 0
        if out:
            out.unlink(missing_ok=True)
            native(out).unlink(missing_ok=True)
    with log.open("a") as f:
        f.write(f"{line}\n{reused} runs of {version_hash[:12]} reused\n")
    return reused, note


def store(
    cache: Path,
    dest: Path,
    arms: tuple[str, ...],
    pipeline: str,
    days: float,
    stale: float | None = None,
    pairs: tuple[str, str] | None = None,
) -> None:
    """Name this job's paid runs for upload and keep them in CACHE (a run older than STALE days gives way); PAIRS (the
    base's and the candidate's hash): also keep the candidate's runs and pinned.jsonl as the pair a re-run continues
    with. A failure here costs a later reuse, never the verdict."""
    try:
        share(dest, pipeline, arms)
        for arm in arms:
            keep(cache, dest / arm, days, stale=stale)
        if pairs:
            for arm, met in (("candidate.jsonl", pairs[0]), ("pinned.jsonl", pairs[1])):
                if (dest / arm).is_file():
                    keep(cache, dest / arm, days, met)
    except Exception as e:  # noqa: BLE001 - see `earlier`
        with (dest / "base.log").open("a") as f:
            f.write(f"runs not kept for later jobs: {type(e).__name__}: {e}\n")


def share(dest: Path, pipeline: str, arms: tuple[str, ...]) -> None:
    """Name each of ARMS (`base.jsonl`, `candidate.jsonl`) with runs this job paid for in DEST/shared.txt
    (`base NAME`), for the CI to upload as an artifact of that name; the candidate only if its version differs from
    the base's."""
    names = {}
    for arm in (a.removesuffix(".jsonl") for a in arms):
        found = read_records(dest / f"{arm}.jsonl")
        paid = {
            (r.get("config_hash"), r.get("set_hash"))
            for r in found
            if r.get("error") is None and not r.get("reused")
        }
        hashes = paid.pop() if len(paid) == 1 else ()
        if all(isinstance(h, str) and h.isalnum() for h in hashes) and hashes:
            n = shared.name(pipeline, *hashes)
            if n not in names.values():
                names[arm] = n
    (dest / "shared.txt").write_text("".join(f"{a} {n}\n" for a, n in names.items()))


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
        f"This request does not change `{p.name}`: its config, prompts and code hash the same in both branches "
        f"(`{config_hash[:12]}`), so nothing ran. Documentation, CI, gate.yaml and the paths it ignores do not count.",
    )
    return PASS


def one(
    p: project.Pipeline,
    golden: Path,
    set_hash: str,
    candidate: Path,
    base: Path | None,
    base_config: str | None,
    prices: str | None,
    dest: Path,
    may_skip: bool = True,
    cache: Path | None = None,
    base_as_usual: bool = False,
) -> int:
    """Compare the target branch's version (`base_config` in `base`) with the request's; without one only the candidate
    runs, for its score and a neutral exit. `may_skip`: an unchanged version may skip the runs. `cache`: keep the runs
    there and share them. `base_as_usual`: the base is prepared as its own branch prepares it, so its runs may come
    from other jobs and go to them; a request that changes `prepare` runs its base for itself alone."""
    if not (candidate / p.config).is_file():
        raise Infra(f"There is no {p.config}.")
    if base is None or base_config is None or not (base / base_config).is_file():
        base = None
    hours, adaptive = p.base_max_age_hours, p.max_spend_usd is not None
    if not hours and not adaptive:
        cache = None  # nothing to reuse: the base runs next to the candidate (D-033)
    keep_days = max(hours / 24, CONTINUE_DAYS if adaptive else 0)
    logs, note, hashes = (dest / "base.log", dest / "candidate.log"), None, (None, None)
    resumable = False  # whether a re-run of an adaptive job can continue
    if base is not None and (may_skip or cache):
        hashes = both(
            lambda: version(base, base_config, logs[0]),
            lambda: version(candidate, p.config, logs[1]),
        )
        if may_skip and hashes[0] and hashes[0] == hashes[1]:
            return unchanged(p, hashes[0], set_hash, dest)
        if cache and adaptive and hashes[1] and hashes[0] != hashes[1]:
            resumable = resume(
                p, cache, hashes, set_hash, golden, dest, logs, keep_days
            )
        if cache and hours and base_as_usual and hashes[0]:
            _, note = earlier(
                p, cache, hashes[0], set_hash, dest / "base.jsonl", logs[0], None if adaptive else p.k, hours / 24,
                keep_days,
            )  # fmt: skip
    runs = [*PYTHON, "-m", "llm_release_gate.runner", "--golden", str(golden), "-k"]

    def run(k: int) -> None:
        codes = both(
            lambda: call([*runs, str(k), "--config", base_config, "--out", str(dest / "base.jsonl")], base, logs[0]) if base else 0,
            lambda: call([*runs, str(k), "--config", p.config, "--out", str(dest / "candidate.jsonl")], candidate, logs[1]),
        )  # fmt: skip
        for arm, code, log in zip(
            ("base version", "candidate"), codes, logs, strict=True
        ):
            if code != 0:
                raise Infra(f"The {arm} did not finish its runs.", log)

    decide = [
        *PYTHON, "-m", "llm_release_gate.gate",
        *(["--base", str(dest / "base.jsonl")] if base else ["--no-base"]), "--candidate", str(dest / "candidate.jsonl"),
        "--golden", str(golden), "--threshold", str(p.delta), "--alpha", str(p.alpha), "--mean", p.mean, "--checks", p.checks,
        *(["--levels", json.dumps(p.levels)] if p.levels else []),
        "--markdown", str(dest / "comment.md"), "--json", str(dest / "verdict.json"),
        *(["--prices", prices] if prices else []),
        *(a for k, flag in BUDGETS.items() if k in p.budgets for a in (flag, str(p.budgets[k]))),
        *(["--max-spend", str(p.max_spend_usd)] if adaptive and base else []),
        *(["--no-resume"] if adaptive and base and not resumable else []),
    ]  # fmt: skip

    def verdict() -> int:
        code = call(decide, candidate, dest / "gate.log")
        if (
            code not in WORST
            or code in (INFRA_ERROR, SET_CHANGED)  # the gate never gives 13
            or not (dest / "comment.md").is_file()
        ):
            raise Infra("The gate could not compare the runs.", dest / "gate.log")
        return code

    try:
        if adaptive and base:
            code = buy(golden, dest, prices, run, verdict)
        else:
            run(
                1 if adaptive else p.k
            )  # no base: one round shows the candidate's score
            code = verdict()
    finally:
        if cache:  # what was paid for is kept, a failed arm's finished runs too
            if (
                adaptive and (dest / "base.jsonl").is_file()
            ):  # the base runs these rounds met, for a re-run
                for src, dst in (
                    (dest / "base.jsonl", dest / "pinned.jsonl"),
                    (native(dest / "base.jsonl"), native(dest / "pinned.jsonl")),
                ):
                    if src.is_file():
                        shutil.copyfile(src, dst)
            arms = (
                ("base.jsonl", "candidate.jsonl")
                if base_as_usual and hours
                else ("candidate.jsonl",)
            )
            pairs = (
                hashes if adaptive and all(hashes) else None
            )  # for a re-run with this cache
            store(cache, dest, arms, p.name, keep_days, hours / 24 or None, pairs)
    if note:
        with (dest / "comment.md").open("a") as f:
            f.write(f"\n{note}\n")
    return code


def resume(
    p: project.Pipeline,
    cache: Path,
    hashes: tuple[str | None, str | None],
    set_hash: str,
    golden: Path,
    dest: Path,
    logs: tuple[Path, Path],
    keep_days: float,
) -> bool:
    """A re-run of an adaptive job continues with the candidate's rounds paid for and the base runs those rounds met, in
    pairs: only the rounds both versions finished, and no other base runs for them, so the checks never read other data
    for rounds they read (D-032) and each round keeps its two runs together (D-033). Returns whether a re-run of this
    job can continue: the job keeps its runs where a later one finds them."""
    base_hash, version_hash = hashes
    routes = (
        {"pinned.jsonl": version_hash, "candidate.jsonl": base_hash}
        if base_hash
        else {}
    )
    _, note = earlier(
        p,
        cache,
        version_hash,
        set_hash,
        None,
        logs[1],
        None,
        CONTINUE_DAYS,
        keep_days,
        routes,
    )
    try:
        k = 0
        if base_hash:
            reuse(
                cache,
                base_hash,
                set_hash,
                CONTINUE_DAYS,
                None,
                dest / "base.jsonl",
                version_hash,
            )
            k = rounds_done(dest / "base.jsonl", [c.id for c in load_cases(golden)])
            kept = [
                r for r in read_records(dest / "base.jsonl") if r["rep"] < k
            ]  # the rounds that pair, no others
            (dest / "base.jsonl").write_text(
                "".join(json.dumps(r) + "\n" for r in kept)
            )
        n = reuse(
            cache,
            version_hash,
            set_hash,
            CONTINUE_DAYS,
            k,
            dest / "candidate.jsonl",
            base_hash,
        )
        line = f"{n} runs of {version_hash[:12]} continued"
    except Exception as e:  # noqa: BLE001 - see `earlier`: without them the job starts over
        line = f"earlier rounds: {type(e).__name__}: {e}"
        for arm in ("base.jsonl", "candidate.jsonl"):
            (dest / arm).unlink(missing_ok=True)
            native(dest / arm).unlink(missing_ok=True)
    with logs[1].open("a") as f:
        f.write(f"{line}\n")
    return (
        note is None and os.environ.get("GITHUB_EVENT_NAME") != "pull_request_target"
    )  # that event shares nothing


def rounds_done(path: Path, cases: list[str]) -> int:
    try:
        return complete(load_arm(path), cases)
    except Mismatch:  # no file or no error-free run
        return 0


def buy(golden: Path, dest: Path, prices: str | None, run, verdict) -> int:
    """The adaptive gate (D-032): buy rounds until the gate decides or the next round does not fit in `max_spend_usd`.
    The gate reads what both versions finished after every step and says in its JSON how many rounds to buy next; before
    a candidate round is priced, one round runs to learn the price."""
    if not prices:
        raise Infra(
            "max_spend_usd needs prices in gate.yaml: without them the gate cannot tell what a round costs."
        )
    cases = [c.id for c in load_cases(golden)]
    if not min(
        rounds_done(dest / arm, cases) for arm in ("base.jsonl", "candidate.jsonl")
    ):
        run(1)
    done = 0
    while True:
        code = verdict()
        a = json.loads((dest / "verdict.json").read_text())["adaptive"]
        if not a["next_rounds"]:
            return code
        if a["rounds"] <= done:
            raise Infra(
                "The rounds did not grow: the gate stopped to avoid a loop.",
                dest / "gate.log",
            )
        done = a["rounds"]
        run(a["rounds"] + a["next_rounds"])


def too_few_runs(p: project.Pipeline) -> str | None:
    """Before any run: a warning if not even one check broken in every run can block with these `k` and `alpha`,
    although the settings let checks block; it names the `k` and the `alpha` that would."""
    if not p.checks_block or p.max_spend_usd is not None:  # adaptive: K_c covers it
        return None
    share = split(p.alpha, True)[1]
    if criterion.can_block(p.k, p.k, share):
        return None
    need = criterion.runs_to_block(share)  # from it on every k can
    # one check passes in all k base runs and fails in all k candidate runs; the checks get half of alpha
    alpha = math.ceil(20_000 * criterion.floor(p.k, p.k)) / 10_000
    return (
        f"⚠️ With alpha {p.alpha:g} and k: {p.k} the rule on checks cannot block: "
        + (f"it needs k: {need}" if need else "no k can")
        + (f", or alpha {alpha:g} at k: {p.k}." if alpha < 0.5 else ".")
    )


def layout(settings: project.Project, directory: Path) -> tuple:
    """What decides which files are a version's code (D-025), the prompts each config names included: a request must
    not change it and skip its own runs."""
    return (
        sorted(settings.ignore),
        own_files(settings, directory),
        settings.defaults.get("prices"),
    )


def snapshot(rules: project.Project, base: Path, to: Path) -> None:
    """Copy the target branch's price files before anything of the request runs in its tree (`prepare`)."""
    for path in {p.prices for p in rules.pipelines.values()} | {
        rules.defaults.get("prices")
    }:
        if path and (base / path).is_file():
            (to / path).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(base / path, to / path)


def ruled(
    p: project.Pipeline,
    rules: project.Project | None,
    candidate: Path,
    base: Path | None,
    prices_copy: Path,
) -> tuple[project.Pipeline, str | None, str | None, list[str]]:
    """`p` under the target branch's rules (D-024), the path of its prices, the target branch's config of the pipeline
    (None: there is no base version) and notes for the comment.

    With a gate.yaml on the target branch the pipeline is matched by name, so renaming a config file does not drop the
    base version; without one, by the request's config path."""
    if base is None:
        return p, str(candidate / p.prices) if p.prices else None, None, []
    if rules is None:
        return p, str(candidate / p.prices) if p.prices else None, p.config, []
    r, own = rules.rules(p), rules.pipelines.get(p.name)
    theirs = None
    if (
        r.prices
    ):  # the copy taken before `prepare`, else a file `prepare` made (not in git)
        theirs = (
            prices_copy / r.prices
            if (prices_copy / r.prices).is_file()
            else base / r.prices
        )
    notes = []
    if own is None:
        notes.append(
            f"`{p.name}` is new in gate.yaml: the target branch's top-level rules apply until merge."
        )
    else:
        changed = any(getattr(r, k) != getattr(p, k) for k in project.SETTINGS)
        if r.prices and p.prices and not changed:
            mine = candidate / p.prices
            changed = not (
                mine.is_file()
                and theirs.is_file()
                and mine.read_bytes() == theirs.read_bytes()
            )
        if changed:
            notes.append(
                f"⚙️ This request changes the gate's rules for `{p.name}` (gate.yaml or its prices). They apply "
                "after merge; until then the gate keeps the target branch's."
            )
    return (
        r,
        str(theirs) if theirs else None,
        own and own.config,
        notes,
    )


def tracked(directory: Path, path: str, committed: bool) -> dict[str, str]:
    """Git's id of each tracked file at PATH, by its path below PATH (a file: ""): as committed, or on disk with
    uncommitted edits, as a version's hash counts them."""

    def listing(*args: str) -> list[str]:
        command = ["git", "--literal-pathspecs", "-C", str(directory), *args]
        done = subprocess.run(
            [*command, "--", path], capture_output=True, text=True, check=False
        )
        if done.returncode:
            raise Infra(f"git cannot list {path}: {done.stderr.strip()}")
        return [e for e in done.stdout.split("\0") if e]

    if committed:
        rows = [e.split("\t", 1) for e in listing("ls-tree", "-z", "-r", "HEAD")]
        found = {n: i.split()[2] for i, n in rows if not i.startswith(GITLINK)}
    else:
        gone = set(listing("ls-files", "-z", "--deleted"))
        rows = [e.split("\t", 1) for e in listing("ls-files", "-z", "--stage")]
        found = {
            n: i.split()[1]
            for i, n in rows
            if not i.startswith(GITLINK) and n not in gone
        }
        edited = [n for n in listing("ls-files", "-z", "--modified") if n in found]
        found |= ids_on_disk(directory, edited)
    prefix = "" if path == "." else path + "/"
    return {n.removeprefix(prefix) if n != path else "": i for n, i in found.items()}


def manifest_ids(path: Path) -> set[str] | None:
    try:
        return {str(i) for i in yaml.safe_load(path.read_text())["ids"]}
    except (OSError, yaml.YAMLError, KeyError, TypeError):
        return None


def set_change(
    own: project.Pipeline | None,
    p: project.Pipeline,
    base: Path | None,
    candidate: Path,
) -> dict | None:
    """What the request changes in the pipeline's test set (D-035), against the set the target branch's gate.yaml
    names: its tracked files, its manifest, and the set itself when both trees hold it (`prepare` may build it). None if
    the target branch defines no set of the pipeline, or the request changes none of it."""
    if base is None or own is None:
        return None
    old_dir, new_dir = posixpath.normpath(own.golden), posixpath.normpath(p.golden)
    files = []
    old = tracked(base, old_dir, True)
    if old:
        new = tracked(candidate, new_dir, False)
        files += [
            posixpath.join(new_dir if k in new else old_dir, k)
            for k in sorted(old.keys() | new.keys())
            if old.get(k) != new.get(k)
        ]
    was = own.manifest and tracked(base, posixpath.normpath(own.manifest), True).get("")
    if was:
        now = p.manifest and tracked(candidate, posixpath.normpath(p.manifest), False)
        if not now or now.get("") != was:
            files.append(p.manifest or own.manifest)
    old_set, new_set = base / own.golden, candidate / p.golden
    old_cases = new_cases = None
    if old_set.is_dir() and new_set.is_dir():
        (old_cases, old_errors), (new_cases, new_errors) = map(
            case_hashes, (old_set, new_set)
        )
        if old_errors or new_errors:  # an invalid set is the gate's error, not a change
            old_cases = new_cases = None
    if not (old or was or old_cases is not None) or not (
        files or old_cases != new_cases
    ):
        return None
    if old_cases is None:  # a set out of git: its manifests name the ids
        old_cases, new_cases = (
            dict.fromkeys(manifest_ids(d / m) or ()) if m else {}
            for d, m in ((base, own.manifest), (candidate, p.manifest))
        )
    return {
        "files": files,
        "added": sorted(new_cases.keys() - old_cases.keys()),
        "removed": sorted(old_cases.keys() - new_cases.keys()),
        "edited": sorted(
            k
            for k in old_cases.keys() & new_cases.keys()
            if old_cases[k] != new_cases[k]
        ),
    }


def named(items: list[str], n: int = 5) -> str:
    return ", ".join(f"`{i}`" for i in items[:n]) + (
        f" and {len(items) - n} more" if len(items) > n else ""
    )


def described(name: str, change: dict) -> str:
    cases = [
        f"{k}: {named(change[k])}" for k in ("added", "removed", "edited") if change[k]
    ]
    return (
        f"✋ This request changes the test set of `{name}`."
        + (f" Cases {'; '.join(cases)}." if cases else "")
        + (f" Files: {named(change['files'])}." if change["files"] else "")
    )


def settle(dest: Path, name: str, change: dict | None, code: int) -> int:
    """Record the set change in the verdict; with one, an exit 0 becomes `set changed` (D-035): the gate compared the
    versions on the request's cases, so a person reviews the edits."""
    verdict = json.loads((dest / "verdict.json").read_text())
    verdict["set_change"] = change and {**change, "outcome": verdict["outcome"]}
    if change and code == PASS:
        title, _, rest = (dest / "comment.md").read_text().partition("\n")
        was = title.removeprefix("**Release gate: ").removesuffix("**")
        (dest / "comment.md").write_text(
            f"**Release gate: ✋ set changed**\n\n{described(name, change)} The gate compares the versions on the "
            "request's cases, so a request could pass by editing the cases that would catch it. Review the edits, "
            f"then merge over the check.\n\nVerdict on the request's cases: {was}.\n{rest}"
        )
        verdict |= {"outcome": "set changed", "exit_code": SET_CHANGED}
        code = SET_CHANGED
    (dest / "verdict.json").write_text(json.dumps(verdict, indent=2) + "\n")
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


def refresh(
    settings: project.Project, tree: Path, out: Path, names: list[str], cache: Path
) -> int:
    """On the target branch: run its version of each pipeline where the cache has no recent runs, and keep them there.
    Compares nothing. Returns 20 if a pipeline failed to run, else 0."""
    log = out / ".prepare-base.log"
    log.unlink(missing_ok=True)
    prepared = ready(tree, settings.prepare, log)
    code = PASS
    for name in names:
        p, dest = settings.pipelines[name], out / name
        try:
            if not prepared:
                raise Infra("The project could not be prepared.", log)
            golden, set_hash = checked_set(p, tree, dest)
            here = version(tree, p.config, dest / "base.log")
            if not here:
                raise Infra("The version's hash cannot be computed.", dest / "base.log")
            if not p.base_max_age_hours:
                print(f"{name}: not cached, base_max_age_hours is 0")
                continue
            adaptive = p.max_spend_usd is not None
            k = k_c(p.alpha, p.checks_block) if adaptive else p.k
            days = p.base_max_age_hours / 24
            keep_days = max(days, CONTINUE_DAYS if adaptive else 0)
            reused, note = earlier(
                p,
                cache / name,
                here,
                set_hash,
                dest / "base.jsonl",
                dest / "base.log",
                k,
                days,
                keep_days,
            )
            if note:
                print(f"{name}: {note}")
            done = call(
                [*PYTHON, "-m", "llm_release_gate.runner", "--golden", str(golden), "-k", str(k),
                 "--config", p.config, "--out", str(dest / "base.jsonl")],
                tree,
                dest / "base.log",
            )  # fmt: skip
            store(cache / name, dest, ("base.jsonl",), name, keep_days)
            if done:
                raise Infra("The runs did not finish.", dest / "base.log")
            print(
                f"{name}: {reused} runs reused, the rest run; version {here[:12]}, set {set_hash[:12]}"
            )
        except Infra as e:
            print(f"{name}: infra error: {e}", file=sys.stderr)
            if e.log and e.log.is_file():
                print(e.log.read_text(errors="replace"), file=sys.stderr)
            code = INFRA_ERROR
        except Exception:  # noqa: BLE001 - a bug is an infra error too, never exit 1
            traceback.print_exc()
            code = INFRA_ERROR
    return code


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
    p.add_argument(
        "--cache",
        type=Path,
        help="a directory for earlier jobs' runs; the gate reuses the target branch's recent runs from it and, on GitHub, "
        "from other jobs' artifacts",
    )
    p.add_argument(
        "--refresh",
        action="store_true",
        help="on the target branch: fill the cache with its version's runs; compares nothing",
    )
    p.add_argument(
        "--rounds",
        type=int,
        help="run both versions this many rounds and decide once, an unchanged version too, in place of k and "
        "max_spend_usd: for measuring noise",
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
    if args.refresh and not (args.cache and args.out):
        p.error("--refresh needs --cache and --out")
    if not (args.refresh or (args.base and args.out)):
        p.error("give --base and --out")
    if args.rounds is not None and (args.rounds < 1 or args.refresh):
        p.error("--rounds needs a count of at least 1 and does not go with --refresh")
    if args.pipeline not in (None, *settings.pipelines):
        p.error(f"gate.yaml has no pipeline {args.pipeline!r}")
    candidate, out = args.project.resolve(), args.out.resolve()
    cache = args.cache.resolve() if args.cache else None
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
    if args.refresh:
        return refresh(settings, candidate, out, names, cache)
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
        problem, rules, rules_problem, removed = None, None, None, []
        same_layout = False  # without the target branch's gate.yaml nothing tells which files a request may ignore
        prices_copy = out / ".base-prices"
        shutil.rmtree(prices_copy, ignore_errors=True)
        if subprocess.run(
            ["git", "worktree", "add", "--detach", str(tree), args.base],
            cwd=root,
            capture_output=True,
            check=False,
        ).returncode:
            problem = Infra(f"Cannot check out the target branch ({args.base}).")
        else:
            if not base.is_dir():  # the request adds the project: every pipeline is new
                base = None
            elif (base / project.FILE).is_file():
                try:
                    rules = project.load(base)
                    snapshot(rules, base, prices_copy)
                    removed = sorted(set(rules.pipelines) - set(settings.pipelines))
                    same_layout = layout(rules, base) == layout(settings, candidate)
                    if not same_layout:
                        rules_problem = (
                            "gate.yaml in this request changes what the gate ignores or which files belong to which "
                            "pipeline, so every pipeline runs."
                        )
                except ValueError as e:
                    rules_problem = f"⚠️ The target branch's gate.yaml is not valid, so this run uses the request's rules: {e}"
            done = both(
                lambda: ready(base, settings.prepare, logs[0]) if base else True,
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
            notes = [rules_problem] if rules_problem else []
            change = None
            try:
                p, prices, base_config, more = ruled(
                    settings.pipelines[name],
                    rules,
                    candidate,
                    base,
                    prices_copy,
                )
                notes += more
                if args.rounds:
                    p = replace(p, k=args.rounds, max_spend_usd=None)
                if warning := too_few_runs(p):  # before the runs cost anything
                    print(f"{name}: {warning}", file=sys.stderr)
                golden, set_hash = checked_set(p, candidate, dest)
                if problem:
                    raise problem
                change = set_change(
                    rules and rules.pipelines.get(name), p, base, candidate
                )
                code = one(
                    p,
                    golden,
                    set_hash,
                    candidate,
                    base,
                    base_config,
                    prices,
                    dest,
                    same_layout and not args.rounds,
                    cache and cache / name,
                    rules is not None and rules.prepare == settings.prepare,
                )
                codes[name] = settle(dest, name, change, code)
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
            if change and codes[name] != SET_CHANGED:
                notes.append(described(name, change))
            if removed:  # unchecked must not look like a pass: a renamed pipeline looks the same (D-025)
                notes.append(
                    f"❌ This request removes {', '.join(f'`{n}`' for n in removed)} from gate.yaml: no version of it "
                    "was compared, so the check fails. If that is intended, merge over the check."
                )
            with (dest / "comment.md").open("a") as f:
                f.writelines(f"\n{note}\n" for note in notes)
            show(dest)
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(tree)],
            cwd=root,
            capture_output=True,
            check=False,
        )
    return min([*codes.values(), *([INCONCLUSIVE] if removed else [])], key=WORST.index)


if __name__ == "__main__":
    sys.exit(main())
