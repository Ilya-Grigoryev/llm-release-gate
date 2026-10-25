import json
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest
from support_agent import web
from test_agent import FakeClient, call

VERSION = {"model": "m", "params": {"temperature": 0}}
SIMULATOR = {"model": "s", "params": {}, "guidelines": "G"}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


@pytest.fixture
def page():
    servers = []

    def start(*replies):
        server = web.serve(
            web.Session(FakeClient(*replies), VERSION, SIMULATOR), "127.0.0.1", 0
        )
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        base = f"http://127.0.0.1:{server.server_port}"

        def request(path, body=None):
            data = None if body is None else json.dumps(body).encode()
            with urllib.request.urlopen(
                urllib.request.Request(base + path, data=data)
            ) as r:
                raw = r.read()
            return raw if path == "/" else json.loads(raw)

        return request

    yield start
    for s in servers:
        s.shutdown()


def settle(request):
    for _ in range(200):
        state = request("/api/state")
        if not state["busy"]:
            return state
        time.sleep(0.01)
    raise AssertionError("the agent did not finish")


def test_the_page_and_the_cases_are_served(page):
    request = page()
    assert b"Workbench" in request("/")
    assert {c["id"] for c in request("/api/cases")} >= {"which-booking", "cancel-late"}
    state = request("/api/state")
    assert state["case"]["id"] == "which-booking" and state["events"][0][
        "text"
    ].startswith("Hi!")


def test_you_play_the_member_and_see_each_tool_call(page):
    request = page(
        [call("find_member", {"email": "jonas.weber@example.com"})],
        [call("list_bookings", {"member_id": "M-102"})],
        "Which one: the room today or the desk tomorrow?",
        [call("cancel_booking", {"booking_id": "B-205"}, id="c2")],
        [
            call(
                "issue_credit",
                {"member_id": "M-102", "amount_eur": 10, "reason": "early"},
                id="c3",
            )
        ],
        "Done: B-205 is cancelled and you have a €10 credit.",
    )
    request("/api/say", {"text": "Cancel my booking please, jonas.weber@example.com"})
    state = settle(request)
    assert [e.get("tool") for e in state["events"]] == [
        None,
        None,
        "find_member",
        "list_bookings",
        None,
    ]
    assert state["events"][1] == {
        "role": "user",
        "text": "Cancel my booking please, jonas.weber@example.com",
    }
    request("/api/say", {"text": "The desk tomorrow"})
    state = settle(request)
    assert state["change"] == {
        "cancelled": ["B-205"],
        "credits": [{"member_id": "M-102", "amount_eur": 10.0}],
    }
    assert state["initial"] == ["B-201", "B-202", "B-203", "B-204", "B-205"]
    assert request("/api/finish", {})["result"]["match"] is True


def test_the_simulated_member_plays_the_case_from_the_start(page):
    request = page("Hi, cancel my booking. ###STOP###")
    request("/api/simulate", {})
    state = settle(request)
    assert state["mode"] == "simulator" and state["stop"] == "user_stop"
    assert state["result"] == {
        "got": {},
        "want": state["result"]["want"],
        "match": False,
    }
    with pytest.raises(urllib.error.HTTPError) as e:
        request("/api/say", {"text": "hello"})
    assert e.value.code == 409


def test_restarting_resets_the_world(page):
    request = page([call("cancel_booking", {"booking_id": "B-205"})], "Cancelled.")
    request("/api/say", {"text": "cancel B-205"})
    assert settle(request)["change"] == {"cancelled": ["B-205"]}
    state = request("/api/start", {"case": "cancel-late"})
    assert (
        state["case"]["id"] == "cancel-late"
        and state["change"] == {}
        and state["count"] == 1
    )


def test_a_failed_model_call_is_shown_and_bad_requests_are_refused(page):
    request = page()  # no replies left: the fake client raises
    request("/api/say", {"text": "hi"})
    assert "IndexError" in settle(request)["error"]
    for path, body in (("/api/say", {"text": " "}), ("/api/start", {"case": "nope"})):
        with pytest.raises(urllib.error.HTTPError) as e:
            request(path, body)
        assert e.value.code == 400


def test_the_page_does_not_import_the_gate():
    code = "import sys, support_agent.web; assert 'llm_release_gate' not in sys.modules"
    subprocess.run([sys.executable, "-c", code], check=True)


def test_malformed_requests_get_a_400(page):
    request = page()
    for path, body in (("/api/state?since=abc", None), ("/api/say", [1])):
        with pytest.raises(urllib.error.HTTPError) as e:
            request(path, body)
        assert e.value.code == 400, path
