import json

import pytest

from llm_release_gate.compare import Arm, Mismatch, load_arm, pair
from llm_release_gate.pipeline import is_alias


def record(case, rep, config="c" * 64, test_set="s" * 64, **extra):
    return {
        "config_hash": config,
        "set_hash": test_set,
        "case": case,
        "rep": rep,
        "scorer_version": "metrics/1",
        "error": None,
        "score": 1.0,
        **extra,
    }


def arm_file(path, records):
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    return load_arm(path)


def test_pairs_cases_in_repetition_order(tmp_path):
    base = arm_file(
        tmp_path / "b.jsonl", [record("x", 1), record("x", 0), record("y", 0)]
    )
    cand = arm_file(
        tmp_path / "c.jsonl",
        [record(c, k, config="d" * 64) for c, k in (("y", 0), ("x", 0), ("x", 1))],
    )
    pairs = pair(base, cand)
    assert list(pairs) == ["x", "y"]
    assert [r["rep"] for r in pairs["x"][0]] == [0, 1]
    assert [r["rep"] for r in pairs["x"][1]] == [0, 1]


def test_refuses_runs_on_different_sets(tmp_path):
    base = arm_file(tmp_path / "b.jsonl", [record("x", 0)])
    cand = arm_file(tmp_path / "c.jsonl", [record("x", 0, test_set="t" * 64)])
    with pytest.raises(Mismatch, match="different test sets"):
        pair(base, cand)


def test_refuses_runs_scored_differently(tmp_path):
    base = arm_file(tmp_path / "b.jsonl", [record("x", 0)])
    cand = arm_file(tmp_path / "c.jsonl", [record("x", 0, scorer_version="metrics/2")])
    with pytest.raises(Mismatch, match="different scorers"):
        pair(base, cand)


def test_refuses_a_case_missing_from_one_arm(tmp_path):
    base = arm_file(tmp_path / "b.jsonl", [record("x", 0), record("y", 0)])
    cand = arm_file(
        tmp_path / "c.jsonl", [record("x", 0), record("y", 0, error="TimeoutError")]
    )
    with pytest.raises(Mismatch, match="one arm only: y"):
        pair(base, cand)


@pytest.mark.parametrize(
    "records, message",
    [
        ([record("x", 0), record("x", 1, config="d" * 64)], "2 config/set pairs"),
        ([record("x", 0), record("x", 1, test_set="t" * 64)], "2 config/set pairs"),
        ([record("x", 0, config=None)], "without a config or set hash"),
        ([record("x", 0), record("x", 1, scorer_version="metrics/2")], "scored by"),
        ([record("x", 0, scorer_version=None)], "without a scorer version"),
        ([record("x", 0, error="boom")], "no error-free records"),
    ],
)
def test_an_arm_is_one_config_on_one_set(tmp_path, records, message):
    with pytest.raises(Mismatch, match=message):
        arm_file(tmp_path / "a.jsonl", records)


def test_the_last_record_of_a_repetition_wins(tmp_path):
    arm = arm_file(tmp_path / "a.jsonl", [record("x", 0, score=0.5), record("x", 0)])
    assert arm.records[("x", 0)]["score"] == 1.0


# models without a date (D-018, T-74)


def alias_arm(model, hour, set_hash="s" * 64):
    records = {
        ("case-1", 0): {
            "case": "case-1",
            "rep": 0,
            "requested_model": model,
            "score": 1.0,
            "timestamp": f"2026-10-25T{hour:02}:00:00+00:00",
        },
    }
    aliases = frozenset({model}) if is_alias(model) else frozenset()
    return Arm("c" * 64, set_hash, "metrics/5", records, aliases)


def test_an_alias_needs_both_arms_run_together():
    pair(alias_arm("gpt-6-luna", 10), alias_arm("gpt-6-luna", 10))
    with pytest.raises(Mismatch, match="no date"):
        pair(alias_arm("gpt-6-luna", 8), alias_arm("gpt-6-luna", 12))
    pair(
        alias_arm("gpt-5.4-mini-2026-03-17", 8),
        alias_arm("gpt-5.4-mini-2026-03-17", 12),
    )  # dated: fine


def test_is_alias():
    assert is_alias("gpt-6-luna") and is_alias("gpt-4.1-mini")
    assert not is_alias("gpt-5.4-mini-2026-03-17") and not is_alias(
        "claude-sonnet-4-5-20250929"
    )
    assert not is_alias(None)
