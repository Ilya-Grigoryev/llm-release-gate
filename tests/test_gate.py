import json
from pathlib import Path

import pytest

from llm_release_gate import gate, runner
from llm_release_gate.golden import load_cases
from llm_release_gate.pipeline import Answer

REPO = Path(__file__).parent.parent
GOLDEN = REPO / "tests" / "fixtures" / "golden"
[CASE] = load_cases(GOLDEN)


@pytest.mark.parametrize(
    "base, candidate, threshold, relative, outcome",
    [
        ({"a": 1.0, "b": 0.5}, {"a": 1.0, "b": 0.5}, 5, False, "pass"),
        ({"a": 1.0, "b": 0.5}, {"a": 1.0, "b": 0.45}, 5, False, "pass"),  # -2.5 points
        (
            {"a": 1.0, "b": 0.5},
            {"a": 1.0, "b": 0.25},
            5,
            False,
            "quality fail",
        ),  # -12.5
        ({"a": 1.0, "b": 0.5}, {"a": 0.95, "b": 0.5}, 5, False, "pass"),  # exactly -2.5
        (
            {"a": 0.8, "b": 0.8},
            {"a": 0.75, "b": 0.8},
            2,
            True,
            "quality fail",
        ),  # -2.5 > 2 % of 0.8
        ({"a": 0.8, "b": 0.8}, {"a": 0.78, "b": 0.8}, 2, True, "pass"),  # -1.0 < 1.6
    ],
)
def test_naive_rule(base, candidate, threshold, relative, outcome):
    v = gate.naive(base, candidate, threshold, relative)
    assert v.outcome == outcome
    assert v.exit_code == (gate.PASS if outcome == "pass" else gate.QUALITY_FAIL)


def test_naive_lists_the_largest_drops_first():
    v = gate.naive({"a": 1, "b": 1, "c": 1}, {"a": 0.75, "b": 0.25, "c": 1}, 5)
    assert [k for k, *_ in v.worse] == ["b", "a"]
    assert v.diff_pp == pytest.approx(-100 / 3)


def test_naive_refuses_different_cases():
    with pytest.raises(ValueError):
        gate.naive({"a": 1.0}, {"b": 1.0}, 5)


def test_exit_codes_are_distinct_and_clear_of_python_and_argparse():
    codes = [
        gate.PASS,
        gate.QUALITY_FAIL,
        gate.INCONCLUSIVE,
        gate.BUDGET_FAIL,
        gate.INFRA_ERROR,
    ]
    assert len(set(codes)) == 5 and not {1, 2} & set(codes)


class Fixed:
    """A fake provider that answers every case with the same fields."""

    def __init__(self, **fields):
        self.output = {**CASE.expected, **fields}

    def run(self, case):
        raw = json.dumps(self.output)
        return Answer(self.output, raw, 100, 20, 0.5, "gpt-4.1-mini-2025-04-14")


def config(tmp_path, name, temperature):
    path = tmp_path / f"{name}.yaml"
    path.write_text(
        "command: [sh, agent.sh]\nmodel: gpt-4.1-mini-2025-04-14\n"
        f"prompt: {REPO / 'tests' / 'fixtures' / 'prompt.md'}\ninput: text\n"
        f"params: {{temperature: {temperature}, seed: 0}}\n"
    )
    return path


def runs(tmp_path, monkeypatch, name, temperature, pipeline, golden=GOLDEN):
    monkeypatch.setattr(runner, "Command", lambda c: pipeline)
    out = tmp_path / f"{name}.jsonl"
    cfg = config(tmp_path, name, temperature)
    runner.main(["--config", str(cfg), "--golden", str(golden), "--out", str(out)])
    return out


def test_end_to_end_without_a_key(tmp_path, monkeypatch, capsys):
    base = runs(tmp_path, monkeypatch, "base", 0, Fixed())
    same = runs(tmp_path, monkeypatch, "same", 1, Fixed(date="01/01/2026 10:00"))
    broken = runs(tmp_path, monkeypatch, "broken", 1, Fixed(total="21.50"))
    capsys.readouterr()

    report = tmp_path / "v.json"
    comment = tmp_path / "c.md"
    args = ["--base", str(base), "--json", str(report), "--markdown", str(comment)]
    assert gate.main([*args, "--candidate", str(same)]) == gate.PASS
    assert json.loads(report.read_text())["outcome"] == "pass"

    assert gate.main([*args, "--candidate", str(broken)]) == gate.QUALITY_FAIL
    verdict = json.loads(report.read_text())
    assert verdict["diff_pp"] == pytest.approx(-25.0)
    assert verdict["base_config"] != verdict["candidate_config"]
    assert (
        "quality fail" in comment.read_text() and "1.000 → 0.750" in comment.read_text()
    )


def test_different_sets_are_an_infra_error(tmp_path, monkeypatch, capsys):
    other = tmp_path / "other"
    other.mkdir()
    (other / "inputs").mkdir()
    for f in (GOLDEN / "inputs").iterdir():
        (other / "inputs" / f.name).write_bytes(f.read_bytes())
    text = (GOLDEN / "synth-001.yaml").read_text().replace("version: 1", "version: 2")
    (other / "synth-001.yaml").write_text(text)
    base = runs(tmp_path, monkeypatch, "base", 0, Fixed())
    cand = runs(tmp_path, monkeypatch, "cand", 1, Fixed(), golden=other)
    code = gate.main(["--base", str(base), "--candidate", str(cand)])
    assert code == gate.INFRA_ERROR
    assert "different test sets" in capsys.readouterr().err


def test_a_missing_score_needs_the_golden_set(tmp_path, monkeypatch, capsys):
    base = runs(tmp_path, monkeypatch, "base", 0, Fixed())
    cand = runs(tmp_path, monkeypatch, "cand", 1, Fixed(total="21.50"))
    records = [json.loads(line) for line in cand.read_text().splitlines()]
    for r in records:  # as if the scorer had failed when the answer was paid for
        r.update(hits=None, score=None, score_error="KeyError: 'total'")
    cand.write_text("".join(json.dumps(r) + "\n" for r in records))
    assert (
        gate.main(["--base", str(base), "--candidate", str(cand)]) == gate.INFRA_ERROR
    )
    assert "pass --golden to rescore" in capsys.readouterr().err
    code = gate.main(
        ["--base", str(base), "--candidate", str(cand), "--golden", str(GOLDEN)]
    )
    assert code == gate.QUALITY_FAIL


def test_a_missing_file_is_an_infra_error_not_a_crash(tmp_path, capsys):
    code = gate.main(
        [
            "--base",
            str(tmp_path / "no.jsonl"),
            "--candidate",
            str(tmp_path / "no.jsonl"),
        ]
    )
    assert code == gate.INFRA_ERROR


@pytest.mark.parametrize(
    "base, candidate, threshold, relative",
    [
        ({"a": 1.0}, {"a": 0.95}, 5, False),  # 1.0 - 0.95 is not exactly 0.05 in floats
        ({"a": 0.7}, {"a": 0.65}, 5, False),
        (
            {f"c{i}": 1.0 for i in range(30)},
            {**{f"c{i}": 1.0 for i in range(30)}, **{f"c{i}": 0.75 for i in range(6)}},
            5,
            False,
        ),
        ({"a": 0.8}, {"a": 0.76}, 5, True),  # 5 % of 0.8 is exactly 4 points
    ],
)
def test_a_drop_exactly_at_the_limit_passes(base, candidate, threshold, relative):
    v = gate.naive(base, candidate, threshold, relative)
    assert v.outcome == "pass" and v.diff_pp == pytest.approx(-v.limit_pp)


@pytest.mark.parametrize(
    "threshold, base, candidate",
    [
        (float("nan"), {"a": 1.0}, {"a": 0.5}),
        (float("inf"), {"a": 1.0}, {"a": 0.5}),
        (-5, {"a": 1.0}, {"a": 1.0}),
        (5, {"a": 1.0}, {"a": float("nan")}),
        (5, {"a": 5.0}, {"a": 1.0}),
        (5, {"a": True}, {"a": 1.0}),
    ],
)
def test_bad_numbers_are_refused(threshold, base, candidate):
    with pytest.raises(ValueError):
        gate.naive(base, candidate, threshold)


def test_the_report_says_how_many_runs_were_there(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(runner, "Command", lambda c: Fixed())
    base = tmp_path / "base.jsonl"
    cfg = config(tmp_path, "base", 0)
    runner.main(
        ["--config", str(cfg), "--golden", str(GOLDEN), "-k", "3", "--out", str(base)]
    )
    cand = runs(tmp_path, monkeypatch, "cand", 1, Fixed())
    report = tmp_path / "v.json"
    assert (
        gate.main(
            ["--base", str(base), "--candidate", str(cand), "--json", str(report)]
        )
        == 0
    )
    assert json.loads(report.read_text())["runs_per_case"] == {
        "base": 3,
        "candidate": 1,
    }
    assert "first run of each version" in capsys.readouterr().out


def test_unwritable_report_and_bad_arguments(tmp_path, monkeypatch, capsys):
    base = runs(tmp_path, monkeypatch, "base", 0, Fixed())
    args = ["--base", str(base), "--candidate", str(base)]
    assert (
        gate.main([*args, "--json", str(tmp_path / "no" / "v.json")])
        == gate.INFRA_ERROR
    )
    with pytest.raises(SystemExit) as e:
        gate.main([*args, "--threshold", "abc"])
    assert e.value.code == 2


def test_a_missing_file_says_so(tmp_path, capsys):
    gate.main(
        [
            "--base",
            str(tmp_path / "no.jsonl"),
            "--candidate",
            str(tmp_path / "no.jsonl"),
        ]
    )
    assert "no such file" in capsys.readouterr().err


def test_a_comment_is_not_left_behind_when_the_verdict_cannot_be_saved(
    tmp_path, monkeypatch, capsys
):
    base = runs(tmp_path, monkeypatch, "base", 0, Fixed())
    comment = tmp_path / "c.md"
    args = ["--base", str(base), "--candidate", str(base), "--markdown", str(comment)]
    assert (
        gate.main([*args, "--json", str(tmp_path / "no" / "v.json")])
        == gate.INFRA_ERROR
    )
    assert not comment.exists()


def test_the_comment_shows_the_limit_at_the_same_precision():
    v = gate.naive({"a": 1.0, "b": 1.0}, {"a": 0.9, "b": 1.0}, 5)
    text = gate.markdown(v, *[gate.Arm("c" * 64, "s" * 64, "metrics/4", {})] * 2)
    assert "(-5.00 points, blocks below -5.00)" in text


def test_the_comment_shows_what_the_decision_cost(tmp_path, monkeypatch, capsys):
    base = runs(tmp_path, monkeypatch, "base", 0, Fixed())
    cand = runs(tmp_path, monkeypatch, "cand", 1, Fixed())
    prices = tmp_path / "prices.yaml"
    # the longest matching prefix wins
    prices.write_text("gpt-4.1: [9, 9]\ngpt-4.1-mini: [0.40, 1.60]\n")
    report, comment = tmp_path / "v.json", tmp_path / "c.md"
    args = ["--base", str(base), "--candidate", str(cand), "--prices", str(prices)]
    args += ["--json", str(report), "--markdown", str(comment)]
    assert gate.main(args) == gate.PASS
    one = (100 * 0.40 + 20 * 1.60) / 1e6  # one case, 100 input and 20 output tokens
    assert json.loads(report.read_text())["cost_usd"] == pytest.approx(
        {"base": one, "candidate": one}
    )
    assert "Cost of this decision $0.000: base $0.000" in comment.read_text()


@pytest.mark.parametrize(
    "prices, code, text",
    [
        ("gpt-5: [1, 1]\n", gate.PASS, "has no price"),
        ("gpt-4.1-mini: [0.40]\n", gate.INFRA_ERROR, None),
        ("gpt-4.1-mini: [-1, 1]\n", gate.INFRA_ERROR, None),
    ],
)
def test_prices_cover_every_model_or_say_so(
    tmp_path, monkeypatch, capsys, prices, code, text
):
    base = runs(tmp_path, monkeypatch, "base", 0, Fixed())
    cand = runs(tmp_path, monkeypatch, "cand", 1, Fixed())
    (tmp_path / "p.yaml").write_text(prices)
    comment = tmp_path / "c.md"
    args = [
        "--base",
        str(base),
        "--candidate",
        str(cand),
        "--prices",
        str(tmp_path / "p.yaml"),
    ]
    assert gate.main([*args, "--markdown", str(comment)]) == code
    assert (text in comment.read_text()) if text else not comment.exists()


@pytest.mark.parametrize(
    "outcome, icon",
    [
        ("pass", "✅"),
        ("quality fail", "❌"),
        ("inconclusive", "⚠️"),
        ("budget fail", "❌"),
    ],
)
def test_the_comment_names_every_outcome(outcome, icon):
    v = gate.Verdict(outcome, 0, 1.0, 1.0, 0.0, 5.0, "rule", 1, [])
    arm = gate.Arm("c" * 64, "s" * 64, "metrics/4", {})
    assert f"**Release gate: {icon} {outcome}**" in gate.markdown(v, arm, arm)


def test_the_comment_warns_about_a_model_without_a_date():
    arm = gate.Arm("c" * 64, "s" * 64, "metrics/5", {}, frozenset({"gpt-6-luna"}))
    v = gate.naive({"a": 1.0}, {"a": 1.0}, 5)
    assert "Model without a date (gpt-6-luna)" in gate.markdown(v, arm, arm)


def test_the_json_report_lists_models_without_a_date(tmp_path, monkeypatch):
    import json as js

    records = []
    for arm in ("base", "candidate"):
        r = {
            "record_version": 4,
            "config_hash": "c" * 64,
            "set_hash": "s" * 64,
            "case": "a",
            "rep": 0,
            "timestamp": "2026-10-25T10:00:00+00:00",
            "requested_model": "gpt-6-luna",
            "model": "gpt-6-luna",
            "scorer_version": "metrics/5",
            "score": 1.0,
            "hits": {"x": True},
            "error": None,
        }
        path = tmp_path / f"{arm}.jsonl"
        path.write_text(js.dumps(r) + "\n")
        records.append(path)
    out = tmp_path / "v.json"
    code = gate.main(
        ["--base", str(records[0]), "--candidate", str(records[1]), "--json", str(out)]
    )
    assert code == 0 and js.loads(out.read_text())["models_without_date"] == [
        "gpt-6-luna"
    ]


def test_without_a_base_the_candidate_is_reported_and_passes(tmp_path, monkeypatch):
    candidate = runs(tmp_path, monkeypatch, "candidate", 0, Fixed())
    prices = tmp_path / "prices.yaml"
    prices.write_text("gpt-4.1-mini-2025-04-14: [1, 1]\n")
    report, comment = tmp_path / "v.json", tmp_path / "c.md"
    args = ["--no-base", "--candidate", str(candidate), "--prices", str(prices)]
    args += [
        "--max-cost-per-run",
        "0.000001",
        "--json",
        str(report),
        "--markdown",
        str(comment),
    ]
    assert gate.main(args) == gate.PASS
    verdict = json.loads(report.read_text())
    assert verdict["outcome"] == "no base" and verdict["candidate_mean"] == 1.0
    assert verdict["budget"]["over"] and verdict["base_config"] is None
    assert "does not block on it" in comment.read_text()


@pytest.mark.parametrize(
    "args", [["--candidate", "c"], ["--base", "b", "--no-base", "--candidate", "c"]]
)
def test_a_base_or_no_base_is_required(args):
    with pytest.raises(SystemExit):
        gate.main(args)


def test_the_age_of_reused_runs_reads_as_hours_or_days():
    assert [gate.ago(d) for d in (0.01, 1 / 24, 5 / 24, 2.04)] == [
        "less than an hour",
        "1 hour",
        "5 hours",
        "2.0 days",
    ]
