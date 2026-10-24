import re
from pathlib import Path

import pytest
import yaml
from support_agent.cases import CATEGORIES, load_cases, reference
from support_agent.world import TOOLS, tool_specs

EXAMPLE = Path(__file__).parent.parent
CASES = load_cases(EXAMPLE / "cases")


def test_ten_cases_cover_every_category():
    assert len(CASES) == 10
    assert {c.category for c in CASES} == set(CATEGORIES)
    assert len({c.id for c in CASES}) == len(CASES)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_reference_actions_make_the_declared_change(case):
    _, change = reference(case)  # a refused tool call raises here
    assert change == case.expect


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_case_ids_match_file_names(case):
    assert (EXAMPLE / "cases" / f"{case.id}.yaml").exists()


def test_tools_file_describes_every_tool():
    specs = tool_specs(EXAMPLE / "tools.yaml")
    assert tuple(s["function"]["name"] for s in specs) == TOOLS
    for s in specs:
        params = s["function"]["parameters"]
        assert set(params["required"]) <= set(params["properties"])


def test_policy_is_short_and_names_real_tools():
    policy = (EXAMPLE / "policy.md").read_text()
    assert 500 <= len(policy.split()) <= 900
    assert set(re.findall(r"`(\w+)`", policy)) <= set(TOOLS)


def test_world_rows_are_valid_yaml():
    world = yaml.safe_load((EXAMPLE / "cases" / "world.yaml").read_text())
    assert {"members", "spaces", "bookings"} <= world.keys()
