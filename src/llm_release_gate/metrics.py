"""Scoring: compare one answer with a case's expected values, as the case's `scoring` block says."""

from collections.abc import Callable
from typing import Any

from llm_release_gate.pipeline import Answer, Case

NORMALISERS: dict[str, Callable[[str], str]] = {
    "whitespace": lambda s: " ".join(s.split()),
    "casefold": str.casefold,
}


def field_match(expected: dict, actual: Any, config: dict) -> dict[str, bool | None]:
    """Each expected field is right if its normalised text equals the answer's.

    A field expected as null has no label and is not scored (None). Fields the case does not expect are ignored.
    """
    steps = config.get("normalise", [])
    if not isinstance(steps, list):
        raise TypeError(f"normalise must be a list, got {steps!r}")
    unknown = [s for s in steps if s not in NORMALISERS]
    if unknown:
        raise ValueError(f"unknown normaliser {unknown}, known: {sorted(NORMALISERS)}")

    def norm(value: Any) -> str:
        text = "" if value is None else str(value)
        for step in steps:
            text = NORMALISERS[step](text)
        return text

    got = actual if isinstance(actual, dict) else {}
    return {
        f: None if want is None else norm(want) == norm(got.get(f))
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
