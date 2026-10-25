"""The browser page over tau2's real orchestrator, environment and evaluator, with the model scripted: no network."""

import json
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest
import tau2_example

if not (tau2_example.DATA / "tau2" / "domains" / "telecom").is_dir():
    pytest.skip("no tau2 data: run sh fetch_data.sh", allow_module_level=True)

from tau2.runner import load_tasks
from tau2_example import web
from test_adapter import (  # noqa: F401 - offline is an autouse fixture
    POLICY,
    TASK,
    offline,
    response,
)
from test_adapter import script as scripted

VERSION = {"model": "fake-model-2026-01-01", "params": {"temperature": 0}}
USER = {"model": "fake-user-2026-01-01", "params": {"temperature": 0}}
PROMPTS = {
    k: (POLICY / f).read_text()
    for k, f in (("main", "main_policy.md"), ("tech_support", "tech_support_manual.md"))
}


script = scripted  # the fixture, under its own name


@pytest.fixture
def page(script):
    servers = []
    tasks = {t.id: t for t in load_tasks("telecom") if t.id == TASK}

    def start(*replies):
        script(list(replies))
        server = web.serve(web.Session(VERSION, USER, PROMPTS, tasks), "127.0.0.1", 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        base = f"http://127.0.0.1:{server.server_port}"

        def request(path, body=None):
            data = None if body is None else json.dumps(body).encode()
            with urllib.request.urlopen(
                urllib.request.Request(base + path, data=data)
            ) as r:
                return json.loads(r.read())

        return request

    yield start
    for s in servers:
        s.shutdown()


def settle(request):
    for _ in range(500):
        state = request("/api/state")
        if not state["busy"]:
            return state
        time.sleep(0.01)
    raise AssertionError("tau2 did not settle")


def test_you_play_the_customer_and_tau2_scores_the_chat(page):
    request = page(
        response(
            calls=[("c1", "get_customer_by_phone", {"phone_number": "555-123-2002"})]
        ),
        response("Please turn on data roaming on your phone."),
        response("Great, your data should work now."),
    )
    state = request("/api/state")
    assert state["your_turn"] and state["events"][0]["role"] == "agent"
    assert (
        state["phone"]["surroundings"]["is_abroad"] and not state["phone"]["data_works"]
    )
    request(
        "/api/say",
        {"text": "My mobile data does not work. I'm John Smith, 555-123-2002."},
    )
    state = settle(request)
    assert [e.get("tool") for e in state["events"] if e.get("tool")] == [
        "get_customer_by_phone"
    ]
    assert (
        state["line"]["line"]["line_id"] == "L1002"
        and state["line"]["line"]["roaming_enabled"]
    )
    request("/api/tap", {"action": "toggle_roaming()"})
    state = settle(request)
    assert (
        state["your_turn"]
        and state["phone"]["device"]["roaming_enabled"]
        and state["phone"]["data_works"]
    )
    assert state["events"][-2:] == [
        {"role": "user", "tool": "toggle_roaming", "args": {}},
        {
            "role": "result",
            "for": "user",
            "text": state["events"][-1]["text"],
            "error": False,
        },
    ]
    request("/api/say", {"text": "Roaming is on now."})
    settle(request)
    request("/api/end", {})
    state = settle(request)
    assert state["done"] and state["result"]["termination"] == "user_stop"
    assert (
        all(a["met"] for a in state["result"]["assertions"])
        and state["result"]["reward"] == 1.0
    )
    # the reward is the end state's: the page says who changed it
    assert state["result"]["basis"] == ["ENV_ASSERTION"]
    assert state["result"]["customer_changes"] == ["toggle_roaming"]
    assert (
        state["result"]["agent_changes"] == [] and state["result"]["agent_lookups"] == 1
    )
    assert state["result"]["expected"] == [{"name": "toggle_roaming", "by": "customer"}]


def test_the_simulated_customer_plays_and_you_cannot_tap(page):
    request = page(response("Hi, my data is down. ###STOP###"))
    state = request("/api/start", {"task": TASK, "mode": "simulator"})
    state = settle(request)
    assert (
        state["mode"] == "simulator"
        and state["done"]
        and state["result"]["reward"] == 0.0
    )
    with pytest.raises(urllib.error.HTTPError) as e:
        request("/api/tap", {"action": "toggle_roaming()"})
    assert e.value.code == 409


def test_restarting_ends_the_old_chat_without_its_verdict(page):
    request = page()
    request("/api/start", {"task": TASK, "mode": "you"})
    time.sleep(0.3)  # the old chat ends and is scored in its own thread
    state = request("/api/state")
    assert state["your_turn"] and state["result"] is None and state["count"] == 1


def test_bad_actions_are_refused(page):
    request = page()
    for action in (
        "toggle_roaming",
        "os.system('x')",
        "fly_to_the_moon()",
        "toggle_roaming(1)",
    ):
        with pytest.raises(urllib.error.HTTPError) as e:
            request("/api/tap", {"action": action})
        assert e.value.code == 400, action


def test_parse_action_reads_keyword_arguments():
    assert web.parse_action(
        'grant_app_permission(app_name="messaging", permission="sms")'
    ) == (
        "grant_app_permission",
        {"app_name": "messaging", "permission": "sms"},
    )


def test_the_page_does_not_import_the_gate():
    code = "import sys, tau2_example.web; assert 'llm_release_gate' not in sys.modules"
    subprocess.run([sys.executable, "-c", code], check=True)
