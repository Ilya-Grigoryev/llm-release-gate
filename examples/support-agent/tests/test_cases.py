import inspect
import re
from pathlib import Path

import pytest
import yaml
from support_agent.agent import STOP
from support_agent.cases import CATEGORIES, load_case, load_cases, reference
from support_agent.world import TOOLS, World, tool_specs

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
        method = inspect.signature(getattr(World, s["function"]["name"])).parameters
        assert list(params["properties"]) == [n for n in method if n != "self"]
        assert params["required"] == [
            n for n, p in method.items() if n != "self" and p.default is p.empty
        ]


def test_policy_is_short_and_names_real_tools():
    policy = (EXAMPLE / "policy.md").read_text()
    assert 550 <= len(policy.split()) <= 900
    assert set(re.findall(r"`(\w+)`", policy)) <= set(TOOLS)


def test_world_rows_are_valid_yaml():
    world = yaml.safe_load((EXAMPLE / "cases" / "world.yaml").read_text())
    assert {"members", "spaces", "bookings"} <= world.keys()


def test_the_simulator_is_part_of_the_test_set():
    sim = yaml.safe_load((EXAMPLE / "cases" / "simulator.yaml").read_text())
    assert set(sim) == {"model", "params", "guidelines"}
    assert STOP in sim["guidelines"]
    assert not (EXAMPLE / "simulator.md").exists()


def test_a_case_adds_rows_to_the_shared_world(tmp_path):
    (tmp_path / "world.yaml").write_text((EXAMPLE / "cases" / "world.yaml").read_text())
    case = yaml.safe_load((EXAMPLE / "cases" / "book-desk.yaml").read_text())
    case["world"] = {
        "bookings": [
            {
                "id": "B-300",
                "member_id": "M-101",
                "space_id": "D-1",
                "start": "2026-11-04T14:00",
                "hours": 1,
                "status": "active",
            }
        ]
    }
    (tmp_path / "busy.yaml").write_text(yaml.safe_dump(case))
    loaded = load_case(tmp_path / "busy.yaml")
    assert loaded.tables["bookings"][-1]["id"] == "B-300"
    assert len(CASES[0].tables["bookings"]) == 5  # the shared file stays as it was
