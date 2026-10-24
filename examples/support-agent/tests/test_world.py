import pytest
from support_agent.world import ToolError, World, diff

TABLES = {
    "members": [
        {"id": "M-1", "name": "A B", "email": "a@x.org", "plan": "Basic"},
    ],
    "spaces": [
        {"id": "D-1", "kind": "desk", "name": "Desk 1", "capacity": 1},
        {"id": "R-1", "kind": "room", "name": "Room", "capacity": 4},
    ],
    "bookings": [
        {
            "id": "B-7",
            "member_id": "M-1",
            "space_id": "D-1",
            "start": "2026-11-03T10:00",
            "hours": 2,
            "status": "active",
        },
    ],
}


def world():
    return World(TABLES, "2026-11-02T09:00")


def test_a_space_cannot_be_double_booked():
    w = world()
    with pytest.raises(ToolError, match="taken"):
        w.create_booking("M-1", "D-1", "2026-11-03T11:00", 1)
    assert w.create_booking("M-1", "D-1", "2026-11-03T12:00", 1)["booking_id"] == "B-8"


@pytest.mark.parametrize(
    "start, hours",
    [
        ("2026-11-02T08:00", 1),
        ("2026-11-03T07:00", 2),
        ("2026-11-03T19:00", 2),
        ("2026-11-03T10:30", 1),
        ("soon", 1),
    ],
)
def test_slots_are_future_whole_hours_within_opening(start, hours):
    with pytest.raises(ToolError):
        world().search_availability("desk", start, hours)


def test_search_skips_busy_and_small_spaces():
    w = world()
    assert w.search_availability("desk", "2026-11-03T10:00", 1) == []
    assert w.search_availability("room", "2026-11-03T10:00", 1, people=5) == []
    assert [
        s["space_id"]
        for s in w.search_availability("room", "2026-11-03T10:00", 1, people=4)
    ] == ["R-1"]


def test_cancel_once_and_only_in_the_future():
    w = world()
    assert w.cancel_booking("B-7")["price_eur"] == 10
    with pytest.raises(ToolError, match="already cancelled"):
        w.cancel_booking("B-7")
    late = World(TABLES, "2026-11-03T10:30")
    with pytest.raises(ToolError, match="started"):
        late.cancel_booking("B-7")


def test_tools_leave_policy_to_the_agent():
    w = world()  # a Basic member may book a room and get any credit: the tools allow it, the policy forbids it
    w.create_booking("M-1", "R-1", "2026-11-04T10:00", 2)
    w.issue_credit("M-1", 999, "no reason")
    assert len(w.state()["credits"]) == 1


def test_bad_calls_become_tool_errors():
    w = world()
    with pytest.raises(ToolError, match="unknown tool"):
        w.call("refund_everything", {})
    with pytest.raises(ToolError, match="bad arguments"):
        w.call("find_member", {"mail": "a@x.org"})
    with pytest.raises(ToolError, match="no member"):
        w.call("find_member", {"email": "nobody@x.org"})
    assert w.call("find_member", {"email": " A@X.org "})["id"] == "M-1"


def test_diff_names_desks_by_kind_and_rooms_by_id():
    w = world()
    before = w.state()
    w.create_booking("M-1", "D-1", "2026-11-04T10:00", 1)
    w.create_booking("M-1", "R-1", "2026-11-04T10:00", 1)
    w.cancel_booking("B-7")
    w.issue_credit("M-1", 10, "early")
    w.escalate_to_human("M-1", "summary")
    assert diff(before, w.state()) == {
        "created": [
            {
                "member_id": "M-1",
                "space": "desk",
                "start": "2026-11-04T10:00",
                "hours": 1,
            },
            {
                "member_id": "M-1",
                "space": "R-1",
                "start": "2026-11-04T10:00",
                "hours": 1,
            },
        ],
        "cancelled": ["B-7"],
        "credits": [{"member_id": "M-1", "amount_eur": 10}],
        "escalations": ["M-1"],
    }


def test_state_is_a_copy():
    w = world()
    w.state()["bookings"].clear()
    assert w.list_bookings("M-1")
    assert TABLES["bookings"][0]["status"] == "active"
