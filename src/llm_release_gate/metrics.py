"""Scoring: compare one answer with a case's expected values, as the case's `scoring` block says."""

import re
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

from llm_release_gate.pipeline import Answer, Case

# Bump when any scorer gives a different verdict for the same answer: records keep it, and runs
# scored by different versions are not compared.
VERSION = 5  # 5: method `checks`, aggregate `all`; field_match unchanged

NORMALISERS: dict[str, Callable[[str], str]] = {
    "whitespace": lambda s: " ".join(s.split()),
    "casefold": str.casefold,
}

MONTHS = {
    m: i
    for i, m in enumerate(
        [
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
        ],
        1,
    )
}
SEP = r"[/.-]"  # no spaces: they would join a date to the receipt text around it
YEAR = r"(\d{4}|\d{2})(?!\d)"
ORDINAL = r"(?:st|nd|rd|th)?"
# (pattern, order): matched with a lookahead so that a failed match does not hide a date it overlaps
PATTERNS = (
    (rf"(?<!\d)(\d{{4}}){SEP}(\d{{1,2}}){SEP}(\d{{1,2}})(?!\d)", "ymd"),
    (rf"(?<!\d)(\d{{1,2}}){SEP}(\d{{1,2}}){SEP}{YEAR}", "dmy"),
    (r"(?<!\d)(\d{8})(?!\d)", "compact"),
    (
        rf"(?<!\d)(\d{{1,2}}){ORDINAL}[\s/.-]*([a-z]{{3}})[a-z]*\.?(?:,\s*|[\s/.-]*){YEAR}",
        "d mon y",
    ),
    (
        rf"\b([a-z]{{3}})[a-z]*\.?[\s/.-]*(\d{{1,2}})(?!\d){ORDINAL}(?:,\s*|[\s/.-]+){YEAR}",
        "mon d y",
    ),
)
PATTERNS = tuple((re.compile(f"(?=({p}))"), order) for p, order in PATTERNS)
SPACED = re.compile(
    r"\s*(\d{1,2})[\s/.-]+(\d{1,2})[\s/.-]+(\d{4}|\d{2})\s*"
)  # the whole value: 05 02 18


def make_date(y: str, m: int | str, d: str) -> date | None:
    year = int(y) + (2000 if len(y) == 2 else 0)
    if not 1990 <= year <= 2099:
        return None
    try:
        return date(year, int(m), int(d))
    except ValueError:
        return None


def from_groups(groups: tuple[str, ...], order: str) -> date | None:
    if order == "compact":  # 20180428 or 25032018
        n = groups[0]
        return make_date(n[:4], n[4:6], n[6:]) or make_date(n[4:], n[2:4], n[:2])
    a, b, c = groups
    if order == "ymd":
        return make_date(a, b, c)
    if order == "dmy":
        return make_date(c, b, a) or make_date(c, a, b)  # day first unless impossible
    if order == "d mon y":
        return make_date(c, MONTHS[b], a) if b in MONTHS else None
    return make_date(c, MONTHS[a], b) if a in MONTHS else None  # mon d y


def parse_date(text: str) -> date | None:
    """The first valid date in the text, by position; None if there is none.

    Numbers join only through `/`, `.` or `-`, and a day needs a separator before the year,
    so `#19- 10/03/2018` gives 10 March and `MAR 2018` gives None. A value that is nothing
    but a date may also use spaces (`05 02 18`).
    """
    t = text.casefold()
    found = sorted(
        (m.start(), k, m.groups()[1:], order)
        for k, (pattern, order) in enumerate(PATTERNS)
        for m in pattern.finditer(t)
    )
    for _, _, groups, order in found:
        if day := from_groups(groups, order):
            return day
    if m := SPACED.fullmatch(t):
        return from_groups(m.groups(), "dmy")
    return None


def parse_number(text: str) -> Decimal | None:
    """An amount such as `9.00`, `RM 7.70`, `$7.80`, `-RM6.42`, `9.00 MYR` or `1,007.50`; None if it is not one."""
    t = "".join(text.split()).casefold()
    m = re.fullmatch(
        r"([+-]?)(?:rm|myr|us\$|\$)?([+-]?)([\d,]+(?:\.\d+)?)(?:rm|myr)?", t
    )
    if not m or (m.group(1) and m.group(2)):
        return None
    sign, digits = m.group(1) or m.group(2), m.group(3)
    if "," in digits:
        if not re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", digits):
            return None
        digits = digits.replace(",", "")
    return Decimal(("-" if sign == "-" else "") + digits)


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


def by_checks(
    expected: dict, actual: Any, config: dict, trace: dict | None = None
) -> dict:
    from llm_release_gate import checks

    return checks.run(expected, actual, config, trace)


METHODS: dict[str, Callable] = {
    "field_match": lambda expected, actual, config, trace=None: field_match(
        expected, actual, config
    ),
    "checks": by_checks,
}
AGGREGATES = ("mean", "all")


def mean(per_field: dict[str, bool | float | None]) -> float | None:
    """Mean over the scored results (True 1, False 0, a share as it is); None if nothing was scored."""
    scored = [float(v) for v in per_field.values() if v is not None]
    return sum(scored) / len(scored) if scored else None


def aggregate(results: dict[str, bool | float | None], how: str) -> float | None:
    """The case's score from its results (D-015): `mean`, or `all` — 1 if every scored result is full, else 0."""
    if how == "mean":
        return mean(results)
    scored = [v for v in results.values() if v is not None]
    return (1.0 if all(float(v) == 1 for v in scored) else 0.0) if scored else None


def score(
    expected: dict, actual: Any, case_config: dict, trace: dict | None = None
) -> dict:
    """{"score": the aggregate, "per_field": {field or check: True/False/share/None}}."""
    if not isinstance(case_config, dict):
        raise TypeError(f"scoring must be a mapping, got {case_config!r}")
    method = METHODS.get(case_config.get("method"))
    if method is None:
        raise ValueError(
            f"unknown scoring method {case_config.get('method')!r}, known: {sorted(METHODS)}"
        )
    how = case_config.get("aggregate", "mean")
    if how not in AGGREGATES:
        raise ValueError(f"aggregate must be one of {AGGREGATES}, got {how!r}")
    per_field = method(expected, actual, case_config, trace)
    return {"score": aggregate(per_field, how), "per_field": per_field}


def hits(case: Case, answer: Answer, trace: dict | None = None) -> dict[str, Any]:
    """Per-field (or per-check) verdicts for the runner; the runner's current trace if none is given."""
    if trace is None:
        from llm_release_gate.trace import current

        t = current()
        trace = None if t is None or t.empty() else t.to_dict()
    return score(case.expected, answer.output, case.scoring, trace)["per_field"]


hits.version = f"metrics/{VERSION}"
