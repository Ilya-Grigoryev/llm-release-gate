"""The support agent in a browser: you play the member, the page shows each tool call and the booking board as it changes.

`uv run --env-file ../../.env python -m support_agent.web`, then open http://127.0.0.1:8765. One chat at a time, the
version under test from `configs/support.yaml`, the world of the chosen case in memory: restarting a case resets it.
"""

import argparse
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yaml
from openai import OpenAI, OpenAIError

from support_agent import agent
from support_agent.cases import load_cases, reference
from support_agent.world import diff, tool_specs

HERE = Path(__file__).resolve().parents[2]
PAGE = Path(__file__).with_name("web.html")
MAX_STEPS = 20  # the gate adapter's limit, so the page runs the version the gate tests
FIRST = "which-booking"


class Busy(Exception):
    pass


class Session:
    """One chat: the case, its world, the agent, and everything that happened so far."""

    def __init__(self, client, version: dict, simulator: dict):
        self.client, self.version, self.simulator = client, version, simulator
        self.policy = (HERE / "policy.md").read_text()
        self.tools = tool_specs(HERE / "tools.yaml")
        self.cases = {c.id: c for c in load_cases(HERE / "cases")}
        self.lock = threading.Lock()  # tool calls against reads of the world
        self.control = (
            threading.Lock()
        )  # one request that starts or ends work at a time
        self.thread = None
        self.start(FIRST if FIRST in self.cases else next(iter(self.cases)))

    @property
    def busy(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def reset(self, case_id: str) -> None:
        if self.busy:
            raise Busy("the agent is still working")
        if case_id not in self.cases:
            raise KeyError(f"no case {case_id}")
        self.case = self.cases[case_id]
        self.world = self.case.world()
        self.before = self.world.state()
        call = self.world.call

        def locked(name, args):
            with self.lock:
                return call(name, args)

        self.world.call = locked
        self.transcript = agent.Transcript()
        self.error = self.result = None
        self.mode = "you"

    def start(self, case_id: str) -> None:
        """You play the member: the agent greets and waits."""
        self.reset(case_id)
        self.agent = agent.Agent(self.client, self.version["model"], self.version["params"], self.policy, self.tools,
                                 self.world, self.transcript, MAX_STEPS)  # fmt: skip
        self.agent.messages.append({"role": "assistant", "content": agent.GREETING})
        self.transcript.events.append({"role": "agent", "text": agent.GREETING})

    def say(self, text: str) -> None:
        if self.busy or self.transcript.stop or self.mode != "you":
            raise Busy("this chat is over: restart the case")
        self.transcript.events.append({"role": "user", "text": text})

        def job():
            if self.agent.respond(text) is None:
                self.transcript.stop = "max_steps"

        self.work(job)

    def simulate(self) -> None:
        """The test set's simulated member plays the case from the start, as in the gate's chat set."""
        self.reset(self.case.id)
        self.mode = "simulator"
        user = {"client": self.client, **self.simulator}

        def job():
            agent.run(self.case, self.world, client=self.client, model=self.version["model"],
                      params=self.version["params"], policy=self.policy, tools=self.tools, user=user,
                      max_steps=MAX_STEPS, transcript=self.transcript)  # fmt: skip
            self.finish()

        self.work(job)

    def finish(self) -> None:
        """Compare the change to the database with the case's reference."""
        with self.lock:
            got = diff(self.before, self.world.state())
        want = reference(self.case)[1]
        self.result = {"got": got, "want": want, "match": got == want}
        if not self.transcript.stop:
            self.transcript.stop = "finished"

    def work(self, job) -> None:
        def run():
            try:
                job()
            except Exception as e:  # noqa: BLE001 - shown on the page, the server keeps running
                self.error = f"{type(e).__name__}: {e}"

        self.error = None
        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()

    def snapshot(self, since: int = 0) -> dict:
        with self.lock:
            tables = self.world.state()
        events = list(self.transcript.events)
        c = self.case
        return {
            "case": {"id": c.id, "category": c.category, "now": c.now, "ticket": c.ticket,
                     "known": c.user["known"].strip(), "instructions": c.user["instructions"].strip()},
            "mode": self.mode,
            "model": self.version["model"],
            "events": events[since:],
            "count": len(events),
            "busy": self.busy,
            "stop": self.transcript.stop,
            "error": self.error,
            "tables": tables,
            "initial": [b["id"] for b in self.before["bookings"]],
            "change": diff(self.before, tables),
            "tokens": self.transcript.tokens,
            "result": self.result,
        }  # fmt: skip


def handler(session: Session):
    class Handler(BaseHTTPRequestHandler):
        def send(self, code: int, body, kind="application/json") -> None:
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            url = urlparse(self.path)
            if url.path == "/":
                self.send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            elif url.path == "/api/cases":
                self.send(200, [{"id": c.id, "category": c.category, "known": c.user["known"].strip()}
                                for c in session.cases.values()])  # fmt: skip
            elif url.path == "/api/state":
                since = parse_qs(url.query).get("since", ["0"])[0]
                if not (since.isascii() and since.isdigit()):
                    return self.send(400, {"error": "since must be a whole number"})
                self.send(200, session.snapshot(int(since)))
            else:
                self.send(404, {"error": "not found"})

        def do_POST(self):
            try:
                size = int(self.headers.get("Content-Length") or 0)
                if size < 0:
                    raise ValueError("Content-Length must not be negative")
                body = json.loads(self.rfile.read(size) or b"{}")
                if not isinstance(body, dict):
                    raise TypeError("send a JSON object")
                path = urlparse(self.path).path
                if path not in (
                    "/api/start",
                    "/api/say",
                    "/api/simulate",
                    "/api/finish",
                ):
                    return self.send(404, {"error": "not found"})
                with session.control:
                    if path == "/api/start":
                        session.start(body["case"])
                    elif path == "/api/say":
                        text = str(body.get("text", "")).strip()
                        if not text:
                            raise ValueError("write a message first")
                        session.say(text)
                    elif path == "/api/simulate":
                        session.simulate()
                    else:
                        if session.busy:
                            raise Busy("the agent is still working")
                        session.finish()
            except Busy as e:
                return self.send(409, {"error": str(e)})
            except (KeyError, TypeError, ValueError) as e:
                return self.send(400, {"error": str(e)})
            self.send(200, session.snapshot())

        def log_message(self, *args):
            pass

    return Handler


def serve(session: Session, host: str, port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), handler(session))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    a = p.parse_args()
    config = yaml.safe_load((HERE / "configs" / "support.yaml").read_text())
    try:
        client = OpenAI(timeout=config.get("timeout_s", 60))
    except OpenAIError as e:
        sys.exit(
            f"{e}\nStart it with the key: uv run --env-file ../../.env python -m support_agent.web"
        )
    version = {"model": config["model"], "params": config.get("params") or {}}
    simulator = yaml.safe_load((HERE / "cases" / "simulator.yaml").read_text())
    server = serve(Session(client, version, simulator), a.host, a.port)
    print(
        f"Workbench support agent ({version['model']}) at http://{a.host}:{server.server_port}  (Ctrl+C stops it)",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
