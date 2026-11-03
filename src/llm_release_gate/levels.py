"""Importance levels of checks (D-028 B). `normal` is the rule on checks as it is; `critical` blocks under either mode
of `checks` and leads the comment; `minor` stays out of the case's score and only warns when significantly worse.

A check's level in a case, first match wins: the case is `minor`; the check's pattern (`critical` before `minor`); the
case's pattern; `normal`. Patterns are shell-style (`assert-*`).
"""

import fnmatch
from collections.abc import Iterable
from dataclasses import dataclass, field

from llm_release_gate.metrics import aggregate

LEVELS = ("critical", "normal", "minor")


@dataclass(frozen=True)
class Levels:
    critical: tuple[str, ...] = ()
    minor: tuple[str, ...] = ()
    # case pattern -> level, first match wins
    cases: dict[str, str] = field(default_factory=dict)

    @classmethod
    def parse(cls, raw: dict | None) -> "Levels":
        raw = raw or {}
        cases = dict(raw.get("cases") or {})
        if bad := sorted(v for v in cases.values() if v not in LEVELS):
            raise ValueError(f"unknown level {bad[0]!r}, known: {', '.join(LEVELS)}")
        return cls(
            tuple(raw.get("critical") or ()), tuple(raw.get("minor") or ()), cases
        )

    def __bool__(self) -> bool:
        return bool(self.critical or self.minor or self.cases)

    def case(self, case: str) -> str | None:
        return next(
            (v for p, v in self.cases.items() if fnmatch.fnmatchcase(case, p)), None
        )

    def of(self, case: str, check: str) -> str:
        own = self.case(case)
        if own == "minor":
            return "minor"
        for level, patterns in (("critical", self.critical), ("minor", self.minor)):
            if any(fnmatch.fnmatchcase(check, p) for p in patterns):
                return level
        return own or "normal"

    def unmatched(self, keys: Iterable[tuple[str, str]]) -> list[str]:
        """Patterns that match no (case, check) of the set: a typo silently leaves its checks `normal`."""
        keys = list(keys)
        out = [
            f"{level}: {p}"
            for level, patterns in (("critical", self.critical), ("minor", self.minor))
            for p in patterns
            if not any(fnmatch.fnmatchcase(check, p) for _, check in keys)
        ]
        out += [
            f"cases: {p}"
            for p in self.cases
            if not any(fnmatch.fnmatchcase(c, p) for c, _ in keys)
        ]
        return out


def case_score(case: str, hits: dict | None, how: str, levels: Levels) -> float | None:
    """The case's score without its `minor` checks; None when nothing else was scored (a `minor` case)."""
    if hits is None:
        return None
    return aggregate(
        {k: v for k, v in hits.items() if levels.of(case, k) != "minor"}, how
    )
