import json
from pathlib import Path
from types import SimpleNamespace

from support_agent import agent
from support_agent.cases import load_case
from support_agent.world import diff, tool_specs

EXAMPLE = Path(__file__).parent.parent
TOOLS = tool_specs(EXAMPLE / "tools.yaml")


def call(name, args, id="c1"):
    arguments = args if isinstance(args, str) else json.dumps(args)
    return SimpleNamespace(
        id=id, function=SimpleNamespace(name=name, arguments=arguments)
    )


class FakeClient:
    """Stands in for `openai.OpenAI`: records requests, answers with canned messages in turn."""

    def __init__(self, *replies):
        self.replies, self.requests = list(replies), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **request):
        self.requests.append(json.loads(json.dumps(request)))
        reply = self.replies.pop(0)
        calls = reply if isinstance(reply, list) else None
        message = SimpleNamespace(content=None if calls else reply, tool_calls=calls)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=10),
            model="fake-2026-01-01",
        )


def solo(case, client, **kw):
    world = case.world()
    before = world.state()
    t = agent.run(
        case,
        world,
        client=client,
        model="m",
        params={"temperature": 0},
        policy="P",
        tools=TOOLS,
        **kw,
    )
    return t, diff(before, world.state())


def test_solo_agent_acts_on_the_ticket():
    case = load_case(EXAMPLE / "cases" / "cancel-late.yaml")
    client = FakeClient(
        [call("find_member", {"email": "jonas.weber@example.com"})],
        [call("cancel_booking", {"booking_id": "B-202"})],
        "Cancelled B-202; no credit, it starts in less than 24 hours.",
    )
    t, change = solo(case, client)
    assert t.stop == "done" and change == case.expect
    assert t.tokens["agent"] == [300, 30] and t.model == {"agent": "fake-2026-01-01"}
    first = client.requests[0]
    assert first["temperature"] == 0 and first["tools"] == TOOLS
    assert first["messages"][0]["content"].startswith("P\n\n## This conversation")
    assert "Monday 2026-11-02 09:00" in first["messages"][0]["content"]
    assert first["messages"][1] == {"role": "user", "content": case.ticket}
    # the model sees each tool result next to its call
    last = client.requests[2]["messages"]
    assert (
        last[-1]["role"] == "tool"
        and json.loads(last[-1]["content"])["status"] == "cancelled"
    )


def test_refusals_and_bad_json_go_back_to_the_model():
    case = load_case(EXAMPLE / "cases" / "overlap.yaml")
    client = FakeClient(
        [
            call("cancel_booking", {"booking_id": "B-999"}),
            call("find_member", "{not json", id="c2"),
        ],
        "Sorry.",
    )
    t, change = solo(case, client)
    assert change == {} and t.stop == "done"
    errors = [e["error"] for e in t.events if "error" in e]
    assert errors[0] == "no booking B-999" and len(errors) == 2
    results = [m for m in client.requests[1]["messages"] if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in results] == ["c1", "c2"]


def test_the_step_limit_stops_a_looping_agent():
    case = load_case(EXAMPLE / "cases" / "overlap.yaml")
    loop = [call("get_member", {"member_id": "M-104"})]
    t, _ = solo(case, FakeClient(loop, loop, loop), max_steps=3)
    assert t.stop == "max_steps" and len(t.events) == 3


def test_chat_runs_until_the_member_stops():
    case = load_case(EXAMPLE / "cases" / "cancel-late.yaml")
    agent_client = FakeClient(
        "Which booking?",
        [call("find_member", {"email": "jonas.weber@example.com"})],
        [call("cancel_booking", {"booking_id": "B-202"})],
        "Done, no credit.",
    )
    user_client = FakeClient(
        "Cancel my room today please.",
        "The 14:00 one, jonas.weber@example.com.",
        "Thanks! ###STOP###",
    )
    user = {
        "client": user_client,
        "model": "u",
        "params": {"temperature": 0},
        "guidelines": "G",
    }
    t, change = solo(case, agent_client, user=user)
    assert t.stop == "user_stop" and change == case.expect
    assert t.tokens["user"] == [300, 30]
    # the member sees the agent as `user`, its scenario in the system prompt, and no tool calls
    seen = user_client.requests[1]["messages"]
    assert seen[0]["content"].startswith("G\n\n## Your scenario\n\nYou are Jonas Weber")
    assert [m["role"] for m in seen[1:]] == ["user", "assistant", "user"]
    assert (
        seen[1]["content"] == agent.GREETING and seen[3]["content"] == "Which booking?"
    )
    assert "tools" not in user_client.requests[0]


def test_chat_stops_after_max_turns():
    case = load_case(EXAMPLE / "cases" / "cancel-late.yaml")
    user = {
        "client": FakeClient("hi", "hi"),
        "model": "u",
        "params": {},
        "guidelines": "G",
    }
    t, _ = solo(case, FakeClient("hello", "hello"), user=user, max_turns=2)
    assert t.stop == "max_turns"
