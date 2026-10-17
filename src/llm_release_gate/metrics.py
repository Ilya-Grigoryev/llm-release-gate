"""Scoring: compare one answer with a case's expected values, as the case's `scoring` block says."""

import re
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

from llm_release_gate.pipeline import Answer, Case

# Bump when any scorer gives a different verdict for the same answer: records keep it, and runs
# scored by different versions are not compared.
VERSION = 3

NORMALISERS: dict[str, Callable[[str], str]] = {
    "whitespace": lambda s: " ".join(s.split()),
    "casefold": str.casefold,
}

MONTHS = {
    m: i
    for i, m in enumerate(
        (
            "jan",
            "feb",
            "mar",
            "apr",
            "may",
            "jun",
            "jul",
            "aug",
            "sep",
            "oct",
            "nov",
            "dec",
        ),
        1,
    )
}
SEP = r"[\s/.-]+"
YEAR = r"(\d{4}|\d{2})(?!\d)"
NUMERIC_DATES = (
    (re.compile(rf"(?<!\d)(\d{{4}}){SEP}(\d{{1,2}}){SEP}(\d{{1,2}})(?!\d)"), "ymd"),
    (re.compile(rf"(?<!\d)(\d{{1,2}}){SEP}(\d{{1,2}}){SEP}{YEAR}"), "dmy"),
    (re.compile(r"(?<!\d)(\d{8})(?!\d)"), "compact"),
)
ORDINAL = r"(?:st|nd|rd|th)?"
DAY_MONTH = re.compile(
    rf"(?<!\d)(\d{{1,2}}){ORDINAL}[\s/.-]*([a-z]{{3}})[a-z]*\.?(?:,\s*|[\s/.-]+){YEAR}"
)
MONTH_DAY = re.compile(
    rf"\b([a-z]{{3}})[a-z]*\.?[\s/.-]*(\d{{1,2}})(?!\d){ORDINAL}(?:,\s*|[\s/.-]+){YEAR}"
)


def make_date(y: str, m: int | str, d: str) -> date | None:
    year = int(y) + (2000 if len(y) == 2 else 0)
    try:
        return date(year, int(m), int(d))
    except ValueError:
        return None


def numeric_date(m: re.Match, order: str) -> date | None:
    if order == "compact":  # 20180428 or 25032018
        n = m.group(1)
        return make_date(n[:4], n[4:6], n[6:]) or make_date(n[4:], n[2:4], n[:2])
    a, b, c = m.groups()
    if order == "ymd":
        return make_date(a, b, c)
    return make_date(c, b, a) or make_date(c, a, b)  # day first unless impossible


def parse_date(text: str) -> date | None:
    """The first valid numeric date in the text, else the first with a month name; None if there is none.

    A day needs a separator before the year, so `MAR 2018` is not a date.
    """
    t = text.casefold()
    numeric = sorted(
        (m.start(), i, m, order)
        for i, (pattern, order) in enumerate(NUMERIC_DATES)
        for m in pattern.finditer(t)
    )
    for *_, m, order in numeric:
        if found := numeric_date(m, order):
            return found
    for pattern, (d, mon, y) in ((DAY_MONTH, (1, 2, 3)), (MONTH_DAY, (2, 1, 3))):
        for m in pattern.finditer(t):
            if m.group(mon) in MONTHS and (
                found := make_date(m.group(y), MONTHS[m.group(mon)], m.group(d))
            ):
                return found
    return None


def parse_number(text: str) -> Decimal | None:
    """An amount such as `9.00`, `RM 7.70`, `$7.80` or `1,007.50`; None if the text is not one."""
    t = re.sub(r"(?i)^(rm|myr|\$)", "", "".join(text.split()))
    if re.fullmatch(r"-?\d{1,3}(,\d{3})+(\.\d+)?", t):
        t = t.replace(",", "")
    return Decimal(t) if re.fullmatch(r"-?\d+(\.\d+)?", t) else None


TYPES: dict[str, Callable[[str], Any] | None] = {
    "string": None,
    "number": parse_number,
    "date": parse_date,
}


def checked_steps(steps: Any) -> list[str]:
    if not isinstance(steps, list):
        raise TypeError(f"normalise must be a list, got {steps!r}")
    unknown = [s for s in steps if s not in NORMALISERS]
    if unknown:
        raise ValueError(f"unknown normaliser {unknown}, known: {sorted(NORMALISERS)}")
    return steps


def field_match(expected: dict, actual: Any, config: dict) -> dict[str, bool | None]:
    """Each expected field is right if the answer has the same value.

    `fields` in the config gives a field its type and normalisers. A number or a date is compared by
    value (`9.0` = `9.00`, `25/12/2018` = `25/12/2018 8:13 PM`); a value that does not parse, and a
    string, is compared as normalised text. A field expected as null has no label and is not scored
    (None). Fields the case does not expect are ignored.
    """
    steps = checked_steps(config.get("normalise", []))
    fields = config.get("fields", {})
    if not isinstance(fields, dict):
        raise TypeError(f"fields must be a mapping, got {fields!r}")
    specs = {}
    for f, spec in fields.items():
        kind = spec.get("type", "string") if isinstance(spec, dict) else None
        if kind not in TYPES:
            raise ValueError(
                f"field {f}: unknown type {kind!r}, known: {sorted(TYPES)}"
            )
        specs[f] = (TYPES[kind], checked_steps(spec.get("normalise", steps)))

    def same(want: Any, got: Any, parse: Callable | None, steps: list[str]) -> bool:
        if parse and (value := parse(str(want))) is not None:
            return got is not None and parse(str(got)) == value
        a, b = str(want), "" if got is None else str(got)
        for step in steps:
            a, b = NORMALISERS[step](a), NORMALISERS[step](b)
        return a == b

    got = actual if isinstance(actual, dict) else {}
    return {
        f: None
        if want is None
        else same(want, got.get(f), *specs.get(f, (None, steps)))
        for f, want in expected.items()
    }


METHODS = {"field_match": field_match}


def mean(per_field: dict[str, bool | None]) -> float | None:
    """Share of right fields among the scored ones; None if no field was scored."""
    scored = [v for v in per_field.values() if v is not None]
    return sum(scored) / len(scored) if scored else None


def score(expected: dict, actual: Any, case_config: dict) -> dict:
    """{"score": mean over scored fields, "per_field": {field: True/False/None}}."""
    if not isinstance(case_config, dict):
        raise TypeError(f"scoring must be a mapping, got {case_config!r}")
    method = METHODS.get(case_config.get("method"))
    if method is None:
        raise ValueError(
            f"unknown scoring method {case_config.get('method')!r}, known: {sorted(METHODS)}"
        )
    per_field = method(expected, actual, case_config)
    return {"score": mean(per_field), "per_field": per_field}


def hits(case: Case, answer: Answer) -> dict[str, bool | None]:
    """Per-field verdicts for the runner."""
    return score(case.expected, answer.output, case.scoring)["per_field"]


hits.version = f"metrics/{VERSION}"
