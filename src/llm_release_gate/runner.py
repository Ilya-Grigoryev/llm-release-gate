"""Run a pipeline K times per case and append one JSON record per (case, repetition).

Each run gets a trace (`trace.Trace`) that holds the steps the program reports; the record keeps them even when the run
fails. `<stem>.native.jsonl` is for raw provider responses, which nothing records yet.
"""

import argparse
import json
import os
import sys
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import asdict, fields
from datetime import UTC, datetime
from pathlib import Path

from llm_release_gate.command import Command
from llm_release_gate.golden import load_cases, validate
from llm_release_gate.hashing import canonical_hash
from llm_release_gate.metrics import aggregate, hits
from llm_release_gate.pipeline import (
    Answer,
    Case,
    Fatal,
    Pipeline,
    Retryable,
    load_config,
)
from llm_release_gate.prices import Prices, load_prices
from llm_release_gate.trace import Trace, active, usage
from llm_release_gate.version import code_hash, commit, version_hash

# 2: scorer_version; 3: trace, usage, wall_s; 4: requested_model; 5: prices_hash
# 6: config_hash covers the project's code (D-025), commit
RECORD_VERSION = 7  # 7: ci_job
Scorer = Callable[[Case, Answer], dict[str, bool | float | None]]
EMPTY_ANSWER = {f.name: None for f in fields(Answer)}


def read_records(path: Path) -> list[dict]:
    """Records in file order. Lines that are not JSON objects (e.g. cut off by a crash) are skipped with a warning."""
    if not path.exists():
        return []
    records, skipped = [], 0
    for line in path.read_text().splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            record = None
        if isinstance(record, dict):
            records.append(record)
        elif line.strip():
            skipped += 1
    if skipped:
        print(
            f"warning: {path}: skipped {skipped} line(s) that are not JSON records",
            file=sys.stderr,
        )
    return records


def results(path: Path, config_hash: str, set_hash: str) -> dict[tuple[str, int], dict]:
    """The last error-free record per (case, repetition) for one config and set."""
    return {
        (r["case"], r["rep"]): r
        for r in read_records(path)
        if r.get("config_hash") == config_hash
        and r.get("set_hash") == set_hash
        and r.get("error") is None
    }


def ci_job(env: Mapping[str, str] = os.environ) -> str | None:
    """The CI job the runs belong to, so runs can be grouped by job; None outside GitHub Actions and GitLab CI.

    On GitHub: repository, run id, attempt and job key; the legs of a matrix job share it.
    """
    if env.get("GITHUB_RUN_ID"):
        keys = (
            "GITHUB_REPOSITORY",
            "GITHUB_RUN_ID",
            "GITHUB_RUN_ATTEMPT",
            "GITHUB_JOB",
        )
        return "github:" + "/".join(env.get(k, "") for k in keys)
    if env.get("CI_JOB_ID"):
        return f"gitlab:{env.get('CI_PROJECT_PATH', '')}/{env['CI_JOB_ID']}"
    return None


def end_line(path: Path) -> None:
    """End a line cut off by a crash so the next record starts on a new line."""
    if not path.exists() or not path.stat().st_size:
        return
    with path.open("rb+") as f:
        f.seek(-1, 2)
        if f.read(1) != b"\n":
            f.write(b"\n")


def call(
    pipeline: Pipeline,
    case: Case,
    max_retries: int,
    wait: Callable[[float], bool],
    trace: Trace | None = None,
) -> tuple[Answer | None, int, str | None]:
    """Run one case, backing off on Retryable. `wait` returns True to stop retrying.

    The pipeline sees `trace` as the current trace; a retried run adds its steps under the next `run_attempt`.
    """
    retries = 0
    while True:
        if trace is not None:
            trace.run_attempt = retries
        try:
            with active(trace):
                return pipeline.run(case), retries, None
        except Retryable as e:
            reason = f"{type(e.__cause__ or e).__name__}: {e}"
            if retries >= max_retries:
                return None, retries, reason
            if wait(min(60, 2**retries)):
                return None, retries, f"stopped during backoff: {reason}"
            retries += 1
        except Fatal:
            raise
        except Exception as e:  # noqa: BLE001 - any pipeline failure becomes a recorded error
            return None, retries, f"{type(e).__name__}: {e}"


def run(
    pipeline: Pipeline,
    cases: Sequence[Case],
    repetitions: int,
    out: Path,
    *,
    config_hash: str,
    set_hash: str,
    score: Scorer,
    workers: int = 4,
    max_retries: int = 5,
    wait: Callable[[float], bool] | None = None,
    prices: Prices | None = None,
    model: str | None = None,
    commit: str | None = None,
) -> int:
    """Append the records missing from `out` and return how many were written.

    A (case, repetition) counts as done if `out` holds a record without a pipeline error
    for the same config and set hash, so a rerun pays only for the rest.
    On Ctrl-C or a Fatal error the queued calls are dropped, backoffs are cut short and
    the calls already running finish and are written. A custom `wait` replaces the
    stop-aware default and is not cut short. `prices` prices the model steps that carry no price;
    `model` is the model the config asks for, kept next to the one the provider reports; `commit` is the project's.
    """
    if type(max_retries) is not int or max_retries < 0:
        raise ValueError(f"max_retries must be a non-negative int, got {max_retries!r}")
    done = results(out, config_hash, set_hash)
    todo = [(c, k) for c in cases for k in range(repetitions) if (c.id, k) not in done]
    run_id, job_id = uuid.uuid4().hex, ci_job()
    stop = threading.Event()
    wait = wait or stop.wait
    out.parent.mkdir(parents=True, exist_ok=True)
    end_line(out)
    native = out.with_name(out.stem + ".native.jsonl")
    end_line(native)
    saved: set[Future] = set()
    written = 0

    def job(case: Case, trace: Trace) -> tuple[Answer | None, int, str | None]:
        start = time.monotonic()
        try:
            return call(pipeline, case, max_retries, wait, trace)
        finally:
            trace.wall_s = round(time.monotonic() - start, 3)

    def outcome(job: Future, trace: Trace) -> tuple[Answer | None, int, str | None]:
        """The job's result; a Fatal error becomes an error record that keeps the partial trace."""
        error = job.exception()
        if isinstance(error, Fatal):
            return None, trace.run_attempt, f"Fatal: {error}"
        return job.result()

    def line(
        job: Future, case: Case, rep: int, trace: Trace
    ) -> tuple[str, dict | None]:
        answer, retries, error = outcome(job, trace)
        if error and trace.stop is None and not trace.empty():
            trace.stop = "error"
        hits = value = score_error = None
        if answer:
            try:
                with active(trace):  # a scorer may check the trace
                    hits = score(case, answer)
                value = aggregate(hits, case.scoring.get("aggregate", "mean"))
            except Exception as e:  # noqa: BLE001 - keep the paid answer, rescore later
                score_error = f"{type(e).__name__}: {e}"
        record = {
            "record_version": RECORD_VERSION,
            "config_hash": config_hash,
            "set_hash": set_hash,
            "commit": commit,
            "case": case.id,
            "rep": rep,
            "run_id": run_id,
            "ci_job": job_id,
            "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
            "requested_model": model,
            # the price table `usage` was computed with
            "prices_hash": canonical_hash(prices) if prices else None,
            **(asdict(answer) if answer else EMPTY_ANSWER),
            "wall_s": trace.wall_s,
            "trace": None if trace.empty() else trace.to_dict(),
            "scorer_version": getattr(score, "version", None),
            "hits": hits,
            "score": value,
            "score_error": score_error,
            "retries": retries,
            "error": error,
        }
        try:
            record["usage"] = (
                usage(record["trace"], prices) if record["trace"] else None
            )
        except Exception as e:  # noqa: BLE001 - a malformed step must not lose the record
            record["usage"] = None
            record["usage_error"] = f"{type(e).__name__}: {e}"
        raw = None
        if trace.native:
            record["trace"]["native"] = native.name
            raw = {
                "run_id": run_id,
                "case": case.id,
                "rep": rep,
                "native": trace.native,
            }
        try:
            return json.dumps(record) + "\n", raw
        except (TypeError, ValueError) as e:
            record["error"] = f"record not serializable: {e}"
            return json.dumps(record, default=repr) + "\n", raw

    def write(
        job: Future, case: Case, rep: int, trace: Trace, reraise: bool = True
    ) -> None:
        nonlocal written
        fatal = job.exception() if isinstance(job.exception(), Fatal) else None
        if fatal and trace.empty():  # nothing was paid for: no record, as before traces
            saved.add(job)
            if reraise:
                raise fatal
            return
        text, raw = line(job, case, rep, trace)
        if (
            raw is not None
        ):  # before the record: a record never points to a missing line
            with native.open("a") as f:
                f.write(json.dumps(raw, default=repr) + "\n")
        with out.open("a") as f:
            f.write(text)
        # mark after the write: an interrupt in between duplicates the record at worst
        saved.add(job)
        written += 1
        if fatal and reraise:
            raise fatal  # the partial trace is written; now stop the run

    pool = ThreadPoolExecutor(workers)
    jobs: dict[Future, tuple[Case, int, Trace]] = {}
    try:
        for c, k in todo:
            trace = Trace()
            jobs[pool.submit(job, c, trace)] = (c, k, trace)
        for done_job in as_completed(jobs):
            write(done_job, *jobs[done_job])
    finally:
        # cancel queued calls before setting stop
        pool.shutdown(wait=False, cancel_futures=True)
        stop.set()
        running = sum(j.running() for j in jobs)
        if running:
            print(f"stopping: waiting for {running} running calls", file=sys.stderr)
        try:
            pool.shutdown()
        finally:
            end_line(out)
            for left, (case, rep, trace) in jobs.items():
                if left in saved or not left.done() or left.cancelled():
                    continue
                if left.exception() and not isinstance(left.exception(), Fatal):
                    continue
                try:
                    write(left, case, rep, trace, reraise=False)
                except Exception as e:  # noqa: BLE001 - one bad record must not lose the others
                    print(f"{case.id}#{rep}: not written: {e}", file=sys.stderr)
    return written


def main(argv: Sequence[str] | None = None) -> None:
    p = argparse.ArgumentParser(
        description="Run one pipeline version over a golden set, K times per case."
    )
    p.add_argument("--config", type=Path, required=True, help="pipeline config (YAML)")
    p.add_argument("--golden", type=Path, required=True, help="golden set directory")
    p.add_argument("-k", type=int, default=1, help="repetitions per case")
    p.add_argument("--out", type=Path, required=True, help="JSONL file to append to")
    p.add_argument("--workers", type=int, default=4, help="parallel calls")
    p.add_argument(
        "--prices",
        type=Path,
        help="YAML `model: [input, output]` or `[input, output, cached input]`, USD per 1M tokens",
    )
    args = p.parse_args(argv)
    if args.k < 1 or args.workers < 1:
        p.error("-k and --workers must be at least 1")
    if not args.golden.is_dir():
        sys.exit(f"{args.golden}: not a directory")
    set_hash, errors = validate(args.golden)
    if errors:
        sys.exit("\n".join(errors))
    try:
        config = load_config(args.config)
        hashes = {"config_hash": version_hash(args.config), "set_hash": set_hash}
        if code_hash(args.config) is None:
            print(
                f"warning: {args.config} is not in git, so its version covers the config and prompts, not the code",
                file=sys.stderr,
            )
        pipeline = Command(config)
        prices = load_prices(args.prices) if args.prices else None
    except (
        ValueError,
        OSError,
        RuntimeError,
    ) as e:  # a bad config, a missing prompt file, a bad price table, an edited file git cannot read
        sys.exit(str(e))
    cases = load_cases(args.golden)
    try:
        written = run(
            pipeline,
            cases,
            args.k,
            args.out,
            score=hits,
            workers=args.workers,
            max_retries=config.max_retries,
            prices=prices,
            model=config.model,
            commit=commit(args.config),
            **hashes,
        )
    except Fatal as e:
        sys.exit(f"stopped: {e}")
    found = results(args.out, **hashes)
    asked = [(c.id, k) for c in cases for k in range(args.k)]
    done = [found[key] for key in asked if key in found]
    scores = [r["score"] for r in done if r["score"] is not None]
    average = f"{sum(scores) / len(scores):.3f}" if scores else "-"
    print(
        f"{written} records written, {len(done)} of {len(asked)} done, "
        f"mean score {average}; config {hashes['config_hash'][:12]}, set {set_hash[:12]}"
    )
    if len(done) < len(asked):
        errors = [r["error"] for r in read_records(args.out) if r.get("error")]
        sys.exit(
            f"not done: {len(asked) - len(done)} of {len(asked)}; last error: {errors[-1] if errors else '-'}"
        )


if __name__ == "__main__":
    main()
