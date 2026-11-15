import json
from pathlib import Path

import pytest

from llm_release_gate import criterion, gate, mean, runner
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


def runs(tmp_path, monkeypatch, name, temperature, pipeline, golden=GOLDEN, k=1):
    monkeypatch.setattr(runner, "Command", lambda c: pipeline)
    out = tmp_path / f"{name}.jsonl"
    cfg = config(tmp_path, name, temperature)
    runner.main(
        ["--config", str(cfg), "--golden", str(golden), "--out", str(out), "-k", str(k)]
    )
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


def test_a_check_broken_in_every_run_blocks_while_the_mean_holds(
    tmp_path, monkeypatch, capsys
):
    base = runs(tmp_path, monkeypatch, "base", 0, Fixed(), k=4)
    broken = runs(tmp_path, monkeypatch, "broken", 1, Fixed(total="21.50"), k=4)
    report, comment = tmp_path / "v.json", tmp_path / "c.md"
    args = ["--base", str(base), "--candidate", str(broken), "--threshold", "30"]
    args += ["--json", str(report), "--markdown", str(comment)]
    assert (
        gate.main(args) == gate.QUALITY_FAIL
    )  # the mean lost 25 points, under the threshold
    checks = json.loads(report.read_text())["checks"]
    assert (checks["outcome"], checks["m"], checks["runs_to_block"]) == ("block", 1, 4)
    [unit] = checks["broken"]
    assert (unit["check"], unit["base"], unit["candidate"]) == ("total", [4, 4], [0, 4])
    text = comment.read_text()
    assert (
        "Checks: 1 broke, they block (one-sided Fisher, α 0.025, on 4 + 4 runs, Tarone m = 1)"
        in text
    )
    assert f"| {CASE.id} | total | 4/4 | 0/4 | 0.014 |" in text

    assert gate.main([*args, "--checks", "report"]) == gate.PASS
    assert json.loads(report.read_text())["checks"]["outcome"] == "report"
    assert "the mode `report` does not block on them" in comment.read_text()


def test_with_one_run_the_comment_says_the_checks_cannot_block(
    tmp_path, monkeypatch, capsys
):
    base = runs(tmp_path, monkeypatch, "base", 0, Fixed())
    broken = runs(tmp_path, monkeypatch, "broken", 1, Fixed(total="21.50"))
    report, comment = tmp_path / "v.json", tmp_path / "c.md"
    args = ["--base", str(base), "--candidate", str(broken), "--threshold", "30"]
    assert (
        gate.main([*args, "--json", str(report), "--markdown", str(comment)])
        == gate.PASS
    )
    checks = json.loads(report.read_text())["checks"]
    assert (checks["testable"], checks["can_block"]) == (0, False)
    assert (
        "with 1 + 1 runs no break can be significant; a single broken check can block from 4 runs of each version "
        "(one-sided Fisher, α 0.025). 1 of 4 passed less often." in comment.read_text()
    )


def test_check_runs_keeps_runs_aligned_and_marks_missing_results():
    pairs = {
        "a": (
            [{"hits": {"x": True}}, {"hits": None, "score_error": "boom"}],
            [{"hits": {"x": False, "y": True}}],
        ),
        "b": ([{}], [{}]),
    }
    base, candidate = gate.check_runs(pairs)
    assert base == {("a", "x"): [True, None], ("a", "y"): [None, None]}
    assert candidate == {("a", "x"): [False], ("a", "y"): [True]}
    assert gate.check_runs({"b": ([{}], [{}])}) == ({}, {})


def test_more_than_five_broken_checks_point_to_the_report():
    base = {(f"c{i}", "x"): [True] * 8 for i in range(7)}
    candidate = {(f"c{i}", "x"): [False] * 8 for i in range(7)}
    line, rows = gate.checks_lines(criterion.per_check(base, candidate))
    assert line.startswith("Checks: 7 broke, they block")
    assert (
        sum(r.startswith("| c") for r in rows) == 5
        and rows[-1] == "2 more in the JSON report."
    )


def lines_for(base, candidate):
    return gate.checks_lines(criterion.per_check(base, candidate))[0]


def test_the_checks_line_follows_the_run_counts_not_the_data():
    def full(k, n, cases=1):
        return {(f"c{i}", "x"): [True] * k + [False] * (n - k) for i in range(cases)}

    assert lines_for(full(8, 8), full(8, 8)).startswith(
        "Checks: none broke (1 checked, one-sided Fisher, α 0.025, on 8 + 8 runs)"
    )
    # two full breaks at 4 + 4: Tarone counts both, and neither can reach 0.025 / 2
    assert lines_for(full(4, 4, 2), full(0, 4, 2)) == (
        "Checks: with 4 + 4 runs no break can be significant; Tarone counts 2 checks that changed or vary, and a break "
        "among them can block from 5 runs of each version (one-sided Fisher, α 0.025). 2 of 2 passed less often."
    )
    # one break and one check that varies the same in both versions: the varying one counts too
    unstable = {("v", "x"): [True, True, False, False]}
    line = lines_for(full(4, 4) | unstable, full(0, 4) | unstable)
    assert "Tarone counts 2 checks" in line and line.endswith(
        "1 of 2 passed less often."
    )
    assert lines_for(full(8, 8), full(6, 8)).startswith(
        "Checks: none significantly worse; 1 of 1 passed less often (one-sided Fisher, α 0.025, on 8 + 8 runs"
    )
    assert "no break can be significant" in lines_for(full(10, 10), full(0, 1))
    assert lines_for(full(10, 10), full(0, 2)).startswith("Checks: 1 broke")


def test_a_check_scored_on_one_side_only_is_counted_even_with_nothing_to_test():
    v = criterion.per_check(
        {("a", "x"): [True], ("a", "y"): [None]},
        {("a", "x"): [None], ("a", "y"): [True]},
    )
    assert gate.checks_lines(v)[0] == (
        "Checks: no check was scored in both versions. 2 checks scored in one version only are left out."
    )


def betting_args(tmp_path, monkeypatch, base, candidate, k, threshold):
    b = runs(tmp_path, monkeypatch, "base", 0, base, k=k)
    c = runs(tmp_path, monkeypatch, "cand", 1, candidate, k=k)
    report, comment = tmp_path / "v.json", tmp_path / "c.md"
    args = [
        "--base",
        str(b),
        "--candidate",
        str(c),
        "--threshold",
        str(threshold),
        "--mean",
        "cases-c0.5",
    ]
    return [*args, "--json", str(report), "--markdown", str(comment)], report, comment


def test_betting_passes_a_silent_candidate_once_it_has_the_runs(
    tmp_path, monkeypatch, capsys
):
    # one case, delta 50 points: each silent run multiplies the capital by 1 + (c / m) * (0.5 - m) = 1.5; 10 runs
    args, report, comment = betting_args(
        tmp_path, monkeypatch, Fixed(), Fixed(date="01/01/2026 10:00"), 10, 50
    )
    assert gate.main(args) == gate.PASS
    v = json.loads(report.read_text())
    assert (v["outcome"], v["mean"]["decided_at"], v["mean"]["runs_for_pass"]) == (
        "pass",
        10,
        10,
    )
    assert v["runs_per_case"] == {"base": 10, "candidate": 10}
    assert v["mean"]["similar_cases"] is None  # one case: no spread over cases
    text = comment.read_text()
    assert (
        "After run 10 of each version the difference lay in" in text
        and "1 cases, 10 runs of each version" in text
    )


def test_betting_blocks_a_broken_candidate(tmp_path, monkeypatch, capsys):
    wrong = Fixed(company="x", date="x", address="x", total="x")  # score 0 in every run
    args, report, comment = betting_args(tmp_path, monkeypatch, Fixed(), wrong, 10, 5)
    assert gate.main(args) == gate.QUALITY_FAIL
    v = json.loads(report.read_text())
    assert (v["outcome"], v["diff_pp"], v["mean"]["outcome"]) == (
        "quality fail",
        -100.0,
        "block",
    )
    assert v["mean"]["upper"] < -0.05
    assert "**Release gate: ❌ quality fail**" in comment.read_text()


def test_betting_with_too_few_runs_is_inconclusive_and_says_what_a_pass_needs(
    tmp_path, monkeypatch, capsys
):
    args, report, comment = betting_args(tmp_path, monkeypatch, Fixed(), Fixed(), 2, 5)
    assert (
        gate.main([*args, "--prices", str(prices_file(tmp_path))]) == gate.INCONCLUSIVE
    )
    v = json.loads(report.read_text())
    assert (v["outcome"], v["mean"]["runs_for_pass"], v["mean"]["decided_at"]) == (
        "inconclusive",
        143,
        None,
    )
    text = comment.read_text()
    assert "**Release gate: ⚠️ inconclusive**" in text
    assert (
        "A pass needs at least 143 runs of each version even if nothing changed (1 case, δ 5 points"
        in text
    )
    assert "141 more, about $" in text


def test_a_broken_check_still_blocks_an_inconclusive_mean(
    tmp_path, monkeypatch, capsys
):
    args, report, _ = betting_args(
        tmp_path, monkeypatch, Fixed(), Fixed(total="21.50"), 4, 5
    )
    assert gate.main(args) == gate.QUALITY_FAIL
    v = json.loads(report.read_text())
    assert (v["mean"]["outcome"], v["checks"]["outcome"]) == ("inconclusive", "block")


def test_betting_takes_the_default_method_and_refuses_relative(
    tmp_path, monkeypatch, capsys
):
    args, report, _ = betting_args(tmp_path, monkeypatch, Fixed(), Fixed(), 2, 5)
    args[args.index("cases-c0.5")] = "betting"
    assert gate.main(args) == gate.INCONCLUSIVE
    v = json.loads(report.read_text())["mean"]
    assert (v["name"], v["method"], v["runs_for_pass"]) == (
        "betting",
        "betting on case runs, c 0.75",
        96,
    )  # E-006
    assert gate.main([*args, "--relative"]) == gate.INFRA_ERROR
    assert "--relative applies to the naive rule only" in capsys.readouterr().err


def prices_file(tmp_path):
    path = tmp_path / "prices.yaml"
    path.write_text("gpt-4.1-mini: [0.40, 1.60]\n")
    return path


def levels_args(tmp_path, monkeypatch, candidate, rules, *extra):
    b = runs(tmp_path, monkeypatch, "base", 0, Fixed(), k=4)
    c = runs(tmp_path, monkeypatch, "cand", 1, candidate, k=4)
    report, comment = tmp_path / "v.json", tmp_path / "c.md"
    args = [
        "--base",
        str(b),
        "--candidate",
        str(c),
        "--golden",
        str(GOLDEN),
        "--threshold",
        "30",
    ]
    args += [
        "--levels",
        json.dumps(rules),
        "--json",
        str(report),
        "--markdown",
        str(comment),
        *extra,
    ]
    return args, report, comment


def test_a_critical_check_blocks_even_when_checks_only_report(
    tmp_path, monkeypatch, capsys
):
    args, report, comment = levels_args(
        tmp_path,
        monkeypatch,
        Fixed(total="21.50"),
        {"critical": ["total"]},
        "--checks",
        "report",
    )
    assert gate.main(args) == gate.QUALITY_FAIL
    lines = comment.read_text().splitlines()
    assert lines[0] == "**Release gate: ❌ quality fail**"
    assert lines[2] == f"❌ Critical checks broke: `total` in {CASE.id}."
    v = json.loads(report.read_text())
    assert [(u["check"], u["level"]) for u in v["checks"]["broken"]] == [
        ("total", "critical")
    ]
    assert v["warnings"] == [] and v["levels"] == {"critical": ["total"]}


def test_a_normal_check_under_report_is_listed_not_blocked(
    tmp_path, monkeypatch, capsys
):
    args, report, comment = levels_args(
        tmp_path,
        monkeypatch,
        Fixed(total="21.50"),
        {"critical": ["company"]},
        "--checks",
        "report",
    )
    assert gate.main(args) == gate.PASS
    v = json.loads(report.read_text())
    assert (
        v["checks"]["broken"] == []
        and v["checks_reported"]["broken"][0]["level"] == "normal"
    )
    assert (
        "Checks that only report (minor; normal under `checks: report`): 1 broke, they only report"
        in (comment.read_text())
    )
    # D-028 B: a normal check under report warns too
    assert [(w["check"], w["level"]) for w in v["warnings"]] == [("total", "normal")]
    assert v["checks_mode"] == "report"
    assert comment.read_text().startswith(
        "**Release gate: ✅ pass · ⚠️ 1 reported check worse**"
    )


def test_a_minor_check_leaves_the_score_and_only_warns(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    args, report, comment = levels_args(
        tmp_path, monkeypatch, Fixed(total="21.50"), {"minor": ["total"]}
    )
    capsys.readouterr()
    assert gate.main(args) == gate.PASS
    v = json.loads(report.read_text())
    assert (v["base_mean"], v["candidate_mean"]) == (
        1.0,
        1.0,
    )  # the three other fields are right
    assert [(w["check"], w["level"], w["candidate"]) for w in v["warnings"]] == [
        ("total", "minor", [0, 4])
    ]
    assert comment.read_text().startswith(
        "**Release gate: ✅ pass · ⚠️ 1 minor check worse**"
    )
    out = capsys.readouterr().out
    assert (
        f"::warning title=Release gate::Minor check total got worse in {CASE.id}: passed 4/4 runs before, 0/4 now"
        in out
    )


def test_without_github_actions_there_is_no_annotation(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    args, _, _ = levels_args(
        tmp_path, monkeypatch, Fixed(total="21.50"), {"minor": ["total"]}
    )
    capsys.readouterr()
    assert gate.main(args) == gate.PASS
    assert "::warning" not in capsys.readouterr().out


def test_a_minor_case_leaves_the_mean_and_every_case_minor_is_refused(
    tmp_path, monkeypatch, capsys
):
    args, _, _ = levels_args(
        tmp_path, monkeypatch, Fixed(), {"cases": {"synth-*": "minor"}}
    )
    assert gate.main(args) == gate.INFRA_ERROR
    assert "every case is minor" in capsys.readouterr().err
    arm = [{"case": "a", "rep": 0, "hits": {"x": True}, "score": 1.0}]
    pairs = {"a": (arm, arm), "b": (arm, arm)}
    kept, minor = gate.leveled(
        pairs,
        gate.levels.Levels.parse({"cases": {"b": "minor"}}),
        {"a": "all", "b": "all"},
    )
    assert (list(kept), minor) == (["a"], ["b"])


def test_levels_that_match_nothing_are_named(tmp_path, monkeypatch, capsys):
    args, report, comment = levels_args(
        tmp_path, monkeypatch, Fixed(), {"critical": ["credit-*"]}
    )
    assert gate.main(args) == gate.PASS
    assert (
        "⚠️ Levels that match no check of this set: critical: credit-*."
        in comment.read_text()
    )
    assert json.loads(report.read_text())["levels_unmatched"] == ["critical: credit-*"]


def test_minor_levels_need_the_golden_set(tmp_path, monkeypatch, capsys):
    args, _, _ = levels_args(tmp_path, monkeypatch, Fixed(), {"minor": ["total"]})
    i = args.index("--golden")
    assert gate.main(args[:i] + args[i + 2 :]) == gate.INFRA_ERROR
    assert "need --golden" in capsys.readouterr().err


def test_an_undecided_rule_with_enough_runs_says_the_runs_did_not_show_it():
    b = {f"c{i}": [1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 1.0, 1.0] for i in range(20)}
    c = {k: [0.0, 1.0, 1.0, 0.0, 1.0, 1.0, 1.0, 0.0] for k in b}
    mv = gate.mean.decide(b, c, 0.05)
    assert mv.outcome == "inconclusive" and mv.runs_for_pass < mv.runs
    [line] = gate.mean_lines(mv, 0.01)
    assert (
        f"these {mv.runs} did not show it: the versions differ, or the noise needs more."
        in line
    )
    assert "$" not in line


def test_the_annotation_escapes_what_github_reads_as_commands(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    args, _, _ = levels_args(
        tmp_path, monkeypatch, Fixed(total="21.50"), {"minor": ["total"]}
    )
    unit = gate.criterion.Unit("50%\ncase", "total", (4, 4), (0, 4), 0.014, 0.014)
    monkeypatch.setattr(gate.Levelled, "warnings", lambda self: [unit])
    capsys.readouterr()
    gate.main(args)
    out = capsys.readouterr().out
    assert "in 50%25%0Acase: passed" in out and "50%\ncase" not in out


def test_the_gate_splits_its_alpha_between_the_rules():
    assert gate.split(0.05, True) == (0.025, 0.025)
    assert gate.split(0.05, False) == (
        0.05,
        0.025,
    )  # no check can block: all for the mean
    assert gate.alpha_line(0.05, True, True) == (
        "False blocks: at most α 0.05 for the gate, 0.025 for the rule on the mean and 0.025 for the rule on checks."
    )
    assert (
        "all of it for the rule on the mean, since no check can block"
        in gate.alpha_line(0.05, True, False)
    )
    assert gate.alpha_line(0.05, False, True) == (
        "False blocks: at most α 0.025 for the rule on checks; the naive rule on the mean has no such bound."
    )
    assert gate.alpha_line(0.05, False, False).startswith(
        "False blocks: no check can block"
    )


@pytest.mark.parametrize("k, code", [(4, gate.PASS), (5, gate.QUALITY_FAIL)])
def test_a_lower_alpha_needs_more_runs_for_a_check_to_block(
    tmp_path, monkeypatch, capsys, k, code
):
    # alpha 0.025 leaves 0.0125 for checks: 4/4 -> 0/4 has p 1/70, above it; 5/5 -> 0/5 has 1/252
    base = runs(tmp_path, monkeypatch, "base", 0, Fixed(), k=k)
    broken = runs(tmp_path, monkeypatch, "broken", 1, Fixed(total="21.50"), k=k)
    report, comment = tmp_path / "v.json", tmp_path / "c.md"
    args = ["--base", str(base), "--candidate", str(broken), "--threshold", "30"]
    args += ["--alpha", "0.025", "--json", str(report), "--markdown", str(comment)]
    assert gate.main(args) == code
    v = json.loads(report.read_text())
    assert v["alpha"] == {"gate": 0.025, "mean": None, "checks": 0.0125}
    assert (v["checks"]["alpha"], v["checks"]["runs_to_block"]) == (0.0125, 5)
    assert (
        "False blocks: at most α 0.0125 for the rule on checks" in comment.read_text()
    )


def test_the_rule_on_the_mean_gets_all_of_alpha_when_no_check_can_block(
    tmp_path, monkeypatch, capsys
):
    args, report, comment = betting_args(tmp_path, monkeypatch, Fixed(), Fixed(), 2, 5)
    gate.main(args)
    v = json.loads(report.read_text())
    assert v["alpha"] == {"gate": 0.05, "mean": 0.025, "checks": 0.025}
    assert v["mean"]["alpha"] == 0.025 and "points (95 %)" in comment.read_text()
    gate.main([*args, "--checks", "report"])
    v = json.loads(report.read_text())
    assert v["alpha"] == {"gate": 0.05, "mean": 0.05, "checks": None}
    assert (
        v["mean"]["alpha"] == 0.05 and v["checks"]["alpha"] == 0.025
    )  # listed at half
    text = comment.read_text()
    assert "all of it for the rule on the mean, since no check can block" in text
    assert "points (90 %)" in text  # 0.05 on each side
    assert "fewer with a larger `alpha` or δ" in text


def test_a_critical_check_keeps_half_of_alpha_under_report(
    tmp_path, monkeypatch, capsys
):
    args, report, _ = levels_args(
        tmp_path, monkeypatch, Fixed(), {"critical": ["total"]}, "--checks", "report"
    )
    gate.main([*args, "--mean", "betting"])
    assert json.loads(report.read_text())["alpha"] == {
        "gate": 0.05,
        "mean": 0.025,
        "checks": 0.025,
    }


@pytest.mark.parametrize("alpha", ["0", "0.5", "-0.1", "nan"])
def test_an_alpha_outside_its_range_is_refused(tmp_path, monkeypatch, capsys, alpha):
    args, _, _ = betting_args(tmp_path, monkeypatch, Fixed(), Fixed(), 2, 5)
    assert gate.main([*args, "--alpha", alpha]) == gate.INFRA_ERROR
    alone = ["--no-base", "--candidate", args[args.index("--candidate") + 1]]
    assert gate.main([*alone, "--alpha", alpha]) == gate.INFRA_ERROR
    assert "alpha must lie in (0, 0.5)" in capsys.readouterr().err


@pytest.mark.parametrize(
    "page", ["README.md", "dashboard/app/docs/how-it-decides/page.mdx"]
)
def test_the_table_of_alpha_follows_the_code(page):
    text = (REPO / page).read_text()
    method = mean.METHODS[mean.DEFAULT]

    def blocks(n, alpha):
        base = {(f"c{i}", "x"): [True] * 5 for i in range(n)}
        broken = {key: [False] * 5 for key in base}
        return criterion.per_check(base, broken, alpha=alpha).outcome == "block"

    for alpha in (0.01, 0.025, 0.05, 0.1):
        on_mean, on_checks = gate.split(alpha, True)
        most = max(n for n in range(1, 30) if blocks(n, on_checks))
        runs = " / ".join(
            str(mean.runs_for_pass(n, 0.05, on_mean, **method)) for n in (10, 30, 50)
        )
        default = " (default)" if alpha == 0.05 else ""
        need = criterion.runs_to_block(on_checks)
        row = f"| {alpha:g}{default} | {on_checks:g} | `k: {need}` | {most} | {runs} |"
        assert row in text


def test_the_pass_floor_names_alpha_only_when_it_could_lower_it():
    def floor(cases):
        same = {f"c{i}": [1.0] for i in range(cases)}
        return gate.mean_lines(mean.decide(same, same, 0.05), None)[0]

    assert "fewer with a larger `alpha` or δ" in floor(1)  # 96 runs
    many = floor(60)  # 2 runs, the first look
    assert "A pass needs at least 2 runs" in many and "fewer with" not in many
