"""Pair the recorded runs of two pipeline versions, case by case. Runs on different test sets are never paired."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from llm_release_gate.pipeline import is_alias
from llm_release_gate.runner import read_records

ALIAS_WINDOW = timedelta(
    hours=1
)  # an alias's two arms must run this close together (D-018)


class Mismatch(ValueError):
    """The two runs cannot be compared."""


@dataclass(frozen=True)
class Arm:
    config_hash: str
    set_hash: str
    scorer_version: str | None
    records: dict[tuple[str, int], dict]  # (case, repetition) -> last error-free record
    aliases: frozenset[str] = field(
        default_factory=frozenset
    )  # requested models without a date

    def span(self) -> tuple[datetime, datetime] | None:
        """When the arm's records were written."""
        times = [
            datetime.fromisoformat(r["timestamp"])
            for r in self.records.values()
            if r.get("timestamp")
        ]
        return (min(times), max(times)) if times else None


def load_arm(path: Path) -> Arm:
    """Read one version's runs: a file must hold one config on one set, scored by one scorer."""
    if not Path(path).is_file():
        raise Mismatch(f"{path}: no such file")
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
        raise Mismatch(f"{path}: records without a scorer version")
    if len(scorers) != 1:
        raise Mismatch(f"{path}: records scored by {sorted(map(str, scorers))}")
    aliases = frozenset(
        r["requested_model"] for r in records if is_alias(r.get("requested_model"))
    )
    return Arm(
        config,
        test_set,
        scorers.pop(),
        {(r["case"], r["rep"]): r for r in records},
        aliases,
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
    aliases = base.aliases | candidate.aliases
    if aliases:
        spans = base.span(), candidate.span()
        if None in spans:
            raise Mismatch(
                f"model {', '.join(sorted(aliases))} has no date and the runs no time"
            )
        (b0, b1), (c0, c1) = spans
        gap = max(b0, c0) - min(b1, c1)
        if gap > ALIAS_WINDOW:
            raise Mismatch(
                f"model {', '.join(sorted(aliases))} has no date, so the provider may have changed it between "
                f"the arms, which ran {gap} apart; run both arms together"
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
