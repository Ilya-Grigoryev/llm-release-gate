"""Run a pipeline K times per case and append one JSON record per (case, repetition)."""

import json
import sys
import threading
import uuid
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import asdict, fields
from datetime import UTC, datetime
from pathlib import Path

from llm_release_gate.pipeline import Answer, Case, Fatal, Pipeline, Retryable

RECORD_VERSION = 1
Scorer = Callable[[Case, Answer], dict[str, bool]]
EMPTY_ANSWER = {f.name: None for f in fields(Answer)}


def read_records(path: Path) -> list[dict]:
    """Records in file order. Lines that are not JSON objects (e.g. cut off by a crash) are skipped."""
    if not path.exists():
        return []
    records = []
    for line in path.read_text().splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
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


def end_line(path: Path) -> None:
    """End a line cut off by a crash so the next record starts on a new line."""
    if not path.exists() or not path.stat().st_size:
        return
    with path.open("rb+") as f:
        f.seek(-1, 2)
        if f.read(1) != b"\n":
            f.write(b"\n")


def call(
    pipeline: Pipeline, case: Case, max_retries: int, wait: Callable[[float], bool]
) -> tuple[Answer | None, int, str | None]:
    """Run one case, backing off on Retryable. `wait` returns True to stop retrying."""
    retries = 0
    while True:
        try:
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
) -> int:
    """Append the records missing from `out` and return how many were written.

    A (case, repetition) counts as done if `out` holds a record without a pipeline error
    for the same config and set hash, so a rerun pays only for the rest.
    On Ctrl-C or a Fatal error the queued calls are dropped, backoffs are cut short and
    the calls already running finish and are written. A custom `wait` replaces the
    stop-aware default and is not cut short.
    """
    if type(max_retries) is not int or max_retries < 0:
        raise ValueError(f"max_retries must be a non-negative int, got {max_retries!r}")
    done = results(out, config_hash, set_hash)
    todo = [(c, k) for c in cases for k in range(repetitions) if (c.id, k) not in done]
    run_id = uuid.uuid4().hex
    stop = threading.Event()
    wait = wait or stop.wait
    out.parent.mkdir(parents=True, exist_ok=True)
    end_line(out)
    saved: set[Future] = set()
    written = 0

    def line(job: Future, case: Case, rep: int) -> str:
        answer, retries, error = job.result()
        hits = value = score_error = None
        if answer:
            try:
                hits = score(case, answer)
                value = sum(hits.values()) / len(hits) if hits else None
            except Exception as e:  # noqa: BLE001 - keep the paid answer, rescore later
                score_error = f"{type(e).__name__}: {e}"
        record = {
            "record_version": RECORD_VERSION,
            "config_hash": config_hash,
            "set_hash": set_hash,
            "case": case.id,
            "rep": rep,
            "run_id": run_id,
            "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
            **(asdict(answer) if answer else EMPTY_ANSWER),
            "hits": hits,
            "score": value,
            "score_error": score_error,
            "retries": retries,
            "error": error,
        }
        try:
            return json.dumps(record) + "\n"
        except (TypeError, ValueError) as e:
            record["error"] = f"record not serializable: {e}"
            return json.dumps(record, default=repr) + "\n"

    def write(job: Future, case: Case, rep: int) -> None:
        nonlocal written
        text = line(job, case, rep)
        with out.open("a") as f:
            f.write(text)
        # mark after the write: an interrupt in between duplicates the record at worst
        saved.add(job)
        written += 1

    pool = ThreadPoolExecutor(workers)
    jobs: dict[Future, tuple[Case, int]] = {}
    try:
        for c, k in todo:
            jobs[pool.submit(call, pipeline, c, max_retries, wait)] = (c, k)
        for job in as_completed(jobs):
            write(job, *jobs[job])
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
            for job, (case, rep) in jobs.items():
                if job in saved or not job.done() or job.cancelled() or job.exception():
                    continue
                try:
                    write(job, case, rep)
                except Exception as e:  # noqa: BLE001 - one bad record must not lose the others
                    print(f"{case.id}#{rep}: not written: {e}", file=sys.stderr)
    return written
