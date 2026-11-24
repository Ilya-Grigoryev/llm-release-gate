"""The adaptive gate (D-032): K_c, the stop rule, the round loop on recorded answers, and what each look reads."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from replay_pipeline import Replay

from llm_release_gate import criterion, gate, mean, pr, runner
from llm_release_gate.compare import Arm
from llm_release_gate.golden import load_cases, validate
from llm_release_gate.metrics import hits

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN = FIXTURES / "golden"
SET_HASH, _ = validate(GOLDEN)
[CASE] = load_cases(GOLDEN)
MODEL = "gpt-4.1-mini-2025-04-14"
RIGHT = Replay().answers[0]
WRONG_DATE = replace(RIGHT, output={**RIGHT.output, "date": "02/02/2026"})


def test_k_c_is_five_unless_alpha_asks_for_more_and_two_without_blocking_checks():
    assert [gate.k_c(a, True) for a in (0.01, 0.025, 0.05, 0.1, 0.4)] == [5] * 5
    assert gate.k_c(0.001, True) == criterion.runs_to_block(0.0005) > 5
    assert gate.k_c(0.05, False) == 2


def test_the_stop_rule_runs_a_round_only_if_its_estimate_fits():
    def at(cost):
        return lambda j: cost

    assert (
        gate.plan(0, 5, 0, 1e-9, lambda j: None) == 1
    )  # no price yet: one round learns it
    assert gate.plan(1, 5, 1, 5, at(1)) == 4  # rounds 2-5 as one batch
    assert gate.plan(1, 5, 1, 4.5, at(1)) == 3  # the limit cuts the batch
    assert gate.plan(5, 5, 5, 7, at(2)) == 1  # after K_c one round at a time
    assert gate.plan(5, 5, 5, 6.9, at(2)) == 0  # the next round does not fit: stop
    assert gate.plan(2, 5, 0, 0.3, at(0.1)) == 3  # a re-run starts with nothing spent
    assert gate.plan(5, 5, 0.5, 0.6, lambda j: 0.1 if j <= 5 else 0.2) == 0


def test_a_round_counts_once_every_case_has_it():
    keys = {("a", 0), ("a", 1), ("a", 2), ("b", 0), ("b", 2)}
    arm = Arm("c", "s", "v", {k: {"case": k[0], "rep": k[1]} for k in keys})
    assert gate.complete(arm, ["a", "b"]) == 1
    assert gate.complete(arm, ["a"]) == 3
    assert gate.complete(arm, []) == 0
    assert set(gate.first_rounds(arm, 2).records) == {("a", 0), ("a", 1), ("b", 0)}


def test_the_pass_forecast_follows_the_capitals_pace():
    silent = [[0.5] * 30] * 3
    steps = mean.capitals(silent, 0.475, 0.025)
    assert mean.pace(steps, 0.025) == mean.runs_for_pass(30, 0.05, 0.025)
    worse = mean.capitals([[0.3] * 30] * 3, 0.475, 0.025)
    assert mean.pace(worse, 0.025) is None


def arm(path, answers, k, config):
    """Run the one-case set up to k rounds on recorded answers, answer i for round i + 1 and the last one after them;
    the runner appends only the rounds missing."""
    done = len(path.read_text().splitlines()) if path.exists() else 0
    runner.run(
        Replay(answers=list(answers[done:]) or list(answers[-1:])),
        [CASE],
        k,
        path,
        config_hash=config * 64,
        set_hash=SET_HASH,
        score=hits,
        wait=lambda s: False,
        model=MODEL,
        workers=1,
    )


@pytest.fixture
def table(tmp_path):
    prices = tmp_path / "prices.yaml"
    prices.write_text(
        f"{MODEL}: [1000, 1000]\n"
    )  # (120 + 40) tokens: $0.16 a run, $0.32 a round of both
    return prices


def args(dest, prices, limit, delta=50, more=()):
    return [
        "--base", str(dest / "base.jsonl"), "--candidate", str(dest / "candidate.jsonl"), "--golden", str(GOLDEN),
        "--threshold", str(delta), "--mean", "betting", "--prices", str(prices), "--max-spend", str(limit),
        "--json", str(dest / "verdict.json"), "--markdown", str(dest / "comment.md"), *more,
    ]  # fmt: skip


def loop(dest, prices, limit, candidate=(RIGHT,), more=()):
    """`pr.buy` on recorded answers: the runner and the gate in this process."""
    asked = []

    def run(k):
        asked.append(k)
        arm(dest / "base.jsonl", [RIGHT], k, "b")
        arm(dest / "candidate.jsonl", list(candidate), k, "c")

    def verdict():
        return gate.main(args(dest, prices, limit, more=more))

    code = pr.buy(GOLDEN, dest, str(prices), run, verdict)
    return (
        code,
        asked,
        json.loads((dest / "verdict.json").read_text()),
        (dest / "comment.md").read_text(),
    )


def test_the_loop_buys_rounds_until_the_gate_decides(tmp_path, table):
    # one case, delta 50: a silent run multiplies the capital by 1.75, so a pass takes 7 rounds
    code, asked, v, comment = loop(tmp_path, table, 10)
    assert code == gate.PASS and v["runs"] == 7 and v["stop"] == "decided"
    assert asked == [
        1,
        5,
        6,
        7,
    ]  # one round to learn the price, a batch to K_c, then one at a time
    assert v["spent_usd"] == pytest.approx(7 * 0.32)
    assert "7 rounds of each version (checks read on rounds 1–5)" in comment


def test_a_limit_before_k_c_decides_nothing_and_a_rerun_continues_with_the_same_runs(
    tmp_path, table
):
    code, asked, v, comment = loop(tmp_path, table, 1)  # three rounds of $0.32 fit
    assert (
        code == gate.INCONCLUSIVE
        and asked == [1, 3]
        and v["runs"] == 3
        and v["stop"] == "limit"
    )
    assert v["checks"] is None and v["budget"] is None  # nothing is read before round 5
    assert "nothing is decided before round 5: 2 more rounds, about $0.64" in comment
    assert "Re-run this job to buy up to $1 more" in comment
    # one case needs 7 rounds when nothing changed, two need 4: K_c makes it 5
    assert (
        "with 1 case a candidate that scores like the base passes at round 7, with 2 cases at round 5"
        in comment
    )
    first = {
        (r["case"], r["rep"]): r["run_id"]
        for r in load_records(tmp_path / "candidate.jsonl")
    }
    code, asked, v, _ = loop(tmp_path, table, 10)
    assert code == gate.PASS and asked == [5, 6, 7] and v["runs"] == 7
    again = {
        (r["case"], r["rep"]): r["run_id"]
        for r in load_records(tmp_path / "candidate.jsonl")
    }
    assert all(
        again[k] == first[k] for k in first
    )  # paid rounds count, and are the same


def test_a_check_broken_in_every_run_blocks_at_k_c(tmp_path, table):
    # the mean alone would need about 28 rounds for this loss; the checks read at round 5 block and name the date
    code, asked, v, comment = loop(
        tmp_path, table, 10, candidate=(WRONG_DATE,), more=("--threshold", "5")
    )
    assert code == gate.QUALITY_FAIL and v["runs"] == 5 and asked == [1, 5]
    assert [u["check"] for u in v["checks"]["broken"]] == ["date"]
    assert (
        "Checks: 1 broke, they block (test over whole runs, α 0.025, on 5 + 5 runs, all 252 splits)"
        in comment
    )


def test_the_checks_read_rounds_1_to_k_c_only(tmp_path, table):
    # the date breaks from round 6 on: over 12 rounds Fisher would name it (p 0.002), on rounds 1-5 it cannot
    arm(tmp_path / "base.jsonl", [RIGHT], 12, "b")
    arm(tmp_path / "candidate.jsonl", [RIGHT] * 5 + [WRONG_DATE] * 7, 12, "c")
    assert (
        gate.main(args(tmp_path, table, 100)) == gate.PASS
    )  # delta 50 tolerates the date: the mean passes
    v = json.loads((tmp_path / "verdict.json").read_text())
    assert v["checks"]["broken"] == [] and v["adaptive"]["k_c"] == 5 and v["runs"] == 12
    fixed = [a for a in args(tmp_path, table, 100) if a not in ("--max-spend", "100")]
    assert (
        gate.main(fixed) == gate.QUALITY_FAIL
    )  # without max_spend_usd the checks read every run, as before


def test_budgets_read_rounds_1_to_k_c_only(tmp_path, table):
    slow = replace(RIGHT, latency_s=30.0)
    arm(tmp_path / "base.jsonl", [RIGHT], 7, "b")
    arm(tmp_path / "candidate.jsonl", [RIGHT] * 5 + [slow] * 2, 7, "c")
    assert (
        gate.main(args(tmp_path, table, 100, more=("--max-latency", "5"))) == gate.PASS
    )
    assert json.loads((tmp_path / "verdict.json").read_text())["budget"]["runs"] == 5


def test_without_prices_the_limit_cannot_be_kept(tmp_path, table, capsys):
    arm(tmp_path / "base.jsonl", [RIGHT], 1, "b")
    arm(tmp_path / "candidate.jsonl", [RIGHT], 1, "c")
    no_prices = [
        a for a in args(tmp_path, table, 1) if a not in ("--prices", str(table))
    ]
    assert gate.main(no_prices) == gate.INFRA_ERROR
    unpriced = tmp_path / "other.yaml"
    unpriced.write_text("some-other-model: [1, 1]\n")
    assert gate.main(args(tmp_path, unpriced, 1)) == gate.INFRA_ERROR
    assert "max_spend_usd cannot be kept" in capsys.readouterr().err
    with pytest.raises(pr.Infra, match="needs prices"):
        pr.buy(GOLDEN, tmp_path, None, lambda k: None, lambda: 0)


def test_no_pass_in_sight_says_so(tmp_path, table):
    # half the fields wrong, delta 30: the capital for a pass shrinks with every round
    worse = replace(
        RIGHT, output={**RIGHT.output, "date": "02/02/2026", "total": "1.00"}
    )
    code, _, v, comment = loop(
        tmp_path,
        table,
        2,
        candidate=(worse,),
        more=("--threshold", "30", "--checks", "report"),
    )
    assert (
        code == gate.INCONCLUSIVE
        and v["stop"] == "limit"
        and v["adaptive"]["pass_rounds"] is None
    )
    assert "no pass is in sight" in comment


def load_records(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_the_gate_buys_at_most_60_rounds(tmp_path):
    free = tmp_path / "free.yaml"
    free.write_text(f"{MODEL}: [0, 0]\n")
    # a loss of exactly delta: neither capital grows, and rounds cost nothing, so only the cap stops it
    more = ("--threshold", "25", "--checks", "report")
    code, asked, v, comment = loop(
        tmp_path, free, 1, candidate=(WRONG_DATE,), more=more
    )
    assert (
        code == gate.INCONCLUSIVE
        and v["runs"] == gate.MAX_ROUNDS
        and v["stop"] == "rounds"
    )
    assert asked[-1] == gate.MAX_ROUNDS and "the most the gate buys" in comment


def test_without_a_way_to_continue_the_comment_says_a_rerun_starts_over(
    tmp_path, table
):
    _, _, v, comment = loop(tmp_path, table, 1, more=("--no-resume",))
    assert v["stop"] == "limit" and not v["adaptive"]["resume"]
    assert (
        "A re-run of this job starts over, as a new test" in comment
        and "Re-run this job to buy" not in comment
    )


def test_the_checks_line_says_why_no_break_can_block_at_k_c():
    # K_c is 2 when no check may block: the checks that only report are read once, on 2 + 2 runs
    base = {(f"c{i}", "x"): [True] * 2 for i in range(30)}
    broken = {key: [False] * 2 for key in base}
    line, _ = gate.checks_lines(criterion.whole_runs(base, broken), once=True)
    assert line == (
        "Checks: read once, on 2 + 2 runs; a check broken in every run can block only from 4 runs of each version "
        "(test over whole runs, α 0.025). 30 of 30 passed less often."
    )
    # 30 checks broken in every run of 5 + 5 block: they share one pattern (Tarone's rule blocked none of them)
    full = {key: [True] * 5 for key in base}
    assert criterion.whole_runs(full, {k: [False] * 5 for k in full}).outcome == "block"
