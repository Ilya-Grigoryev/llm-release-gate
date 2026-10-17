"""Pair the recorded runs of two pipeline versions, case by case. Runs on different test sets are never paired."""

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from llm_release_gate.runner import read_records


class Mismatch(ValueError):
    """The two runs cannot be compared."""


@dataclass(frozen=True)
class Arm:
    config_hash: str
    set_hash: str
    scorer_version: str | None
    records: dict[tuple[str, int], dict]  # (case, repetition) -> last error-free record


def load_arm(path: Path) -> Arm:
    """Read one version's runs: a file must hold one config on one set, scored by one scorer."""
    records = [r for r in read_records(path) if r.get("error") is None]
    if not records:
        raise Mismatch(f"{path}: no error-free records")
    ids = {(r.get("config_hash"), r.get("set_hash")) for r in records}
    if len(ids) != 1:
        raise Mismatch(f"{path}: runs of {len(ids)} config/set pairs, expected one")
    [(config, test_set)] = ids
    if not config or not test_set:
        raise Mismatch(f"{path}: records without a config or set hash")
    scorers = {r.get("scorer_version") for r in records}
    if None in scorers:
        raise Mismatch(f"{path}: records without a scorer version (record version 1)")
    if len(scorers) != 1:
        raise Mismatch(f"{path}: records scored by {sorted(map(str, scorers))}")
    return Arm(
        config, test_set, scorers.pop(), {(r["case"], r["rep"]): r for r in records}
    )


def pair(base: Arm, candidate: Arm) -> dict[str, tuple[list[dict], list[dict]]]:
    """Per case, the base and the candidate records in repetition order.

    Raises Mismatch if the arms ran on different sets, were scored differently or do not cover the same cases.
    """
    if base.set_hash != candidate.set_hash:
        raise Mismatch(
            f"different test sets: {base.set_hash[:12]} and {candidate.set_hash[:12]}"
        )
    if base.scorer_version != candidate.scorer_version:
        raise Mismatch(
            f"different scorers: {base.scorer_version} and {candidate.scorer_version}"
        )
    b, c = by_case(base), by_case(candidate)
    one_sided = sorted(b.keys() ^ c.keys())
    if one_sided:
        raise Mismatch(f"cases with runs in one arm only: {', '.join(one_sided)}")
    return {case: (b[case], c[case]) for case in sorted(b)}


def by_case(arm: Arm) -> dict[str, list[dict]]:
    out = defaultdict(list)
    for (case, _), record in sorted(arm.records.items()):
        out[case].append(record)
    return out
