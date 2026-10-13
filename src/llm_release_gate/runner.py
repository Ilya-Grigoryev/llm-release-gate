"""Run a pipeline K times per case and append one JSON record per (case, repetition)."""

import json
import time
import uuid
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, fields
from datetime import UTC, datetime
from pathlib import Path

from llm_release_gate.pipeline import Answer, Case, Pipeline, Retryable

Scorer = Callable[[Case, Answer], dict[str, bool]]
EMPTY_ANSWER = {f.name: None for f in fields(Answer)}


def read_records(path: Path) -> list[dict]:
    """Records in file order. A line cut off by a crash is skipped."""
    if not path.exists():
        return []
    records = []
    for line in path.read_text().splitlines():
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def call(
    pipeline: Pipeline, case: Case, max_retries: int, sleep: Callable[[float], None]
) -> tuple[Answer | None, int, str | None]:
    """Run one case; back off and repeat on Retryable. Returns (answer, retries, error)."""
    retries = 0
    while True:
        try:
            return pipeline.run(case), retries, None
        except Retryable as e:
            if retries == max_retries:
                return None, retries, f"{type(e.__cause__ or e).__name__}: {e}"
            sleep(min(60, 2**retries))
            retries += 1
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
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Append the records missing from `out` and return how many were written.

    A (case, repetition) counts as done if `out` holds a record for it with the same
    config and set hash and no error, so a rerun after a crash or an error picks up
    only the rest.
    """
    done = {
        (r["case"], r["rep"])
        for r in read_records(out)
        if r["config_hash"] == config_hash
        and r["set_hash"] == set_hash
        and r["error"] is None
    }
    todo = [(c, k) for c in cases for k in range(repetitions) if (c.id, k) not in done]
    run_id = uuid.uuid4().hex
    out.parent.mkdir(parents=True, exist_ok=True)
    pool = ThreadPoolExecutor(workers)
    try:
        with out.open("a") as f:
            jobs = {
                pool.submit(call, pipeline, c, max_retries, sleep): (c, k)
                for c, k in todo
            }
            for job in as_completed(jobs):
                case, rep = jobs[job]
                answer, retries, error = job.result()
                hits = (
                    score(case, answer)
                    if answer and answer.output is not None
                    else None
                )
                record = {
                    "config_hash": config_hash,
                    "set_hash": set_hash,
                    "case": case.id,
                    "rep": rep,
                    "run_id": run_id,
                    "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
                    **(asdict(answer) if answer else EMPTY_ANSWER),
                    "hits": hits,
                    "score": sum(hits.values()) / len(hits) if hits else None,
                    "retries": retries,
                    "error": error,
                }
                f.write(json.dumps(record) + "\n")
                f.flush()
    finally:
        # On Ctrl-C or a crash, drop the queued calls instead of paying for them.
        pool.shutdown(cancel_futures=True)
    return len(todo)
