from dataclasses import replace

import pytest

from llm_release_gate import project


def load(tmp_path, text):
    (tmp_path / "gate.yaml").write_text(text)
    return project.load(tmp_path)


def test_a_pipelines_settings_win_over_the_top_ones(tmp_path):
    p = load(
        tmp_path,
        "prepare: [npm, ci]\nk: 3\ndelta: 2\nbase_max_age_days: 3\n"
        "pipelines:\n"
        "  chat: {config: c.yaml, golden: g, k: 5, manifest: m.yaml, inputs-url: 'https://x/{name}', base_max_age_days: 0}\n"
        "  docs: {config: d.yaml, golden: h}\n",
    )
    assert p.prepare == ("npm", "ci")
    chat, docs = p.pipelines["chat"], p.pipelines["docs"]
    assert (chat.k, chat.delta, chat.manifest, chat.inputs_url) == (
        5,
        2,
        "m.yaml",
        "https://x/{name}",
    )
    assert (docs.k, docs.delta, docs.prices, docs.budgets) == (3, 2, None, {})
    assert (chat.base_max_age_days, docs.base_max_age_days) == (0, 3)


def test_defaults(tmp_path):
    [p] = load(
        tmp_path, "pipelines: {a: {config: c.yaml, golden: g}}\n"
    ).pipelines.values()
    assert (p.k, p.delta, p.prices, p.budgets, p.base_max_age_days) == (
        1,
        5.0,
        None,
        {},
        7,
    )


@pytest.mark.parametrize(
    "text, error",
    [
        ("pipelines: {}\n", "pipelines: {} should be non-empty"),
        ("pipelines: {a: {golden: g}}\n", "missing pipelines.a.config"),
        (
            "pipelines: {a: {config: c, golden: g, confg: x}}\n",
            "pipelines.a: Additional properties are not allowed ('confg'",
        ),
        ("pipelines: {'..': {config: c, golden: g}}\n", "'..' does not match"),
        ("pipelines: {1: {config: c, golden: g}}\n", "1 is not of type 'string'"),
        ("pipelines: {.a: {config: c, golden: g}}\n", "'.a' does not match"),
        (
            "pipelines: {a: {config: c, golden: g}}\nk: 0\n",
            "k: 0 is less than the minimum of 1",
        ),
        (
            "pipelines: {a: {config: c, golden: g}}\nk: 2.0\n",
            "k: 2.0 is not of type 'integer'",
        ),
        ("pipelines: {a b: {config: c, golden: g}}\n", "does not match"),
        (
            "pipelines: {a: {config: c, golden: g}}\nbase_max_age_days: -1\n",
            "base_max_age_days: -1 is less than the minimum of 0",
        ),
        (
            "pipelines: {a: {config: c, golden: g}}\nbase_max_age_days: .inf\n",
            "base_max_age_days: inf is greater than the maximum of 365",
        ),
        (
            "pipelines: {a: {config: c, golden: g}}\nprepare: npm ci\n",
            "prepare: 'npm ci' is not of type 'array'",
        ),
        (
            "pipelines: {a: {config: c, golden: g, budgets: {cost_per_run_usd: 1}}}\n",
            "budgets.cost_per_run_usd needs prices",
        ),
        ("[a, b]\n", "is not of type 'object'"),
        (
            "pipelines: {a: {config: c, golden: g}}\nbudgets: {cost_per_run_usd: 1}\n",
            "budgets.cost_per_run_usd needs prices",
        ),
        ("pipelines: [\n", "gate.yaml"),
        (
            "pipelines: {a: {config: c, golden: g}}\nmax_spend_usd: 5\nprices: p.yaml\n",
            "pipelines.a: max_spend_usd needs mean: betting",
        ),
        (
            "pipelines: {a: {config: c, golden: g, mean: betting, max_spend_usd: 5}}\n",
            "pipelines.a: max_spend_usd needs prices",
        ),
        (
            "pipelines: {a: {config: c, golden: g}}\nmax_spend_usd: 0\n",
            "max_spend_usd: 0 is less than or equal to the minimum of 0",
        ),
    ],
)
def test_errors_name_the_file_and_the_field(tmp_path, text, error):
    with pytest.raises(ValueError, match="gate.yaml") as e:
        load(tmp_path, text)
    assert error in str(e.value)


def test_a_missing_file_is_named(tmp_path):
    with pytest.raises(ValueError, match="gate.yaml: No such file"):
        project.load(tmp_path)


def test_a_bad_value_is_the_only_error(tmp_path):
    with pytest.raises(ValueError) as e:
        load(tmp_path, "pipelines: {a: {config: c, golden: g, delta: '5'}}\n")
    assert str(e.value).endswith("pipelines.a.delta: '5' is not of type 'number'")


def test_rules_for_a_pipeline_and_for_one_the_project_lacks(tmp_path):
    rules = load(tmp_path, "k: 3\npipelines: {a: {config: c, golden: g, delta: 2}}\n")
    request = project.Pipeline("a", "c2.yaml", "g2", delta=50, k=1)
    a = rules.rules(request)
    assert (a.config, a.golden, a.delta, a.k) == ("c2.yaml", "g2", 2, 3)
    new = rules.rules(project.Pipeline("b", "b.yaml", "gb", delta=50))
    assert (new.delta, new.k) == (5.0, 3)


def test_the_rule_on_checks_blocks_unless_set_to_report(tmp_path):
    p = load(
        tmp_path,
        "checks: report\npipelines:\n  a: {config: c, golden: g}\n  b: {config: c, golden: g, checks: block}\n",
    )
    assert (p.pipelines["a"].checks, p.pipelines["b"].checks) == ("report", "block")
    [d] = load(tmp_path, "pipelines: {a: {config: c, golden: g}}\n").pipelines.values()
    assert d.checks == "block"
    with pytest.raises(ValueError, match="checks"):
        load(tmp_path, "pipelines: {a: {config: c, golden: g}}\nchecks: maybe\n")


def test_the_rule_on_the_mean_is_naive_unless_set_to_betting(tmp_path):
    p = load(
        tmp_path,
        "mean: betting\npipelines:\n  a: {config: c, golden: g}\n  b: {config: c, golden: g, mean: naive}\n",
    )
    assert (p.pipelines["a"].mean, p.pipelines["b"].mean) == ("betting", "naive")
    [d] = load(tmp_path, "pipelines: {a: {config: c, golden: g}}\n").pipelines.values()
    assert d.mean == "naive"
    with pytest.raises(ValueError, match="mean"):
        load(tmp_path, "mean: welch\npipelines: {a: {config: c, golden: g}}\n")


def test_levels_are_a_rule_of_the_project(tmp_path):
    p = load(
        tmp_path,
        "levels: {critical: [state], minor: ['assert-*'], cases: {'probe-*': minor}}\n"
        "pipelines:\n  a: {config: c, golden: g}\n  b: {config: c, golden: g, levels: {}}\n",
    )
    assert p.pipelines["a"].levels == {
        "critical": ["state"],
        "minor": ["assert-*"],
        "cases": {"probe-*": "minor"},
    }
    assert p.pipelines["b"].levels == {}
    with pytest.raises(ValueError, match="levels"):
        load(
            tmp_path,
            "levels: {cases: {a: low}}\npipelines: {a: {config: c, golden: g}}\n",
        )
    with pytest.raises(ValueError, match="levels"):
        load(tmp_path, "levels: {major: [x]}\npipelines: {a: {config: c, golden: g}}\n")


def test_alpha_is_the_whole_gates_and_stays_below_one_half(tmp_path):
    rules = load(
        tmp_path,
        "alpha: 0.01\npipelines: {a: {config: c, golden: g}, b: {config: d, golden: g, alpha: 0.1}}\n",
    )
    assert (rules.pipelines["a"].alpha, rules.pipelines["b"].alpha) == (0.01, 0.1)
    assert project.Pipeline("c", "c", "g").alpha == 0.05
    for bad in ("0", "0.5", ".nan"):
        with pytest.raises(ValueError, match="alpha"):
            load(
                tmp_path, f"alpha: {bad}\npipelines: {{a: {{config: c, golden: g}}}}\n"
            )


def test_a_spend_limit_makes_the_runs_adaptive_and_k_c_follows_the_settings(tmp_path):
    p = load(
        tmp_path,
        "pipelines: {a: {config: c, golden: g}, b: {config: c, golden: g, checks: report}}\n"
        "mean: betting\nprices: p.yaml\nmax_spend_usd: 2.5\n",
    )
    a, b = p.pipelines["a"], p.pipelines["b"]
    assert (
        a.max_spend_usd == b.max_spend_usd == 2.5
        and "max_spend_usd" in project.SETTINGS
    )
    assert a.checks_block and not b.checks_block
    assert replace(b, levels={"critical": ["x"]}).checks_block
    assert replace(b, levels={"cases": {"x-*": "critical"}}).checks_block
