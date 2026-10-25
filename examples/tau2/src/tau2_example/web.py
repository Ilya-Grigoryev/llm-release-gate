"""tau2's telecom agent in a browser: you play the customer, chat with tau2's own agent and work the phone yourself.

`uv run --env-file ../../.env python -m tau2_example.web`, then open http://127.0.0.1:8766. tau2's orchestrator, agent,
environment and evaluator run unchanged; only the customer is you instead of the simulator, or the simulator of the
golden set if you hand it over. The agent is the version under test of `configs/telecom.yaml`.
"""

import argparse
import ast
import json
import queue
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yaml
from pydantic import BaseModel
from tau2.data_model.message import AssistantMessage, ToolCall, ToolMessage, UserMessage
from tau2.evaluator.evaluator import EvaluationType
from tau2.orchestrator.orchestrator import Orchestrator
from tau2.runner import (
    build_agent,
    build_environment,
    build_user,
    load_tasks,
    run_simulation,
)
from tau2.user.user_simulator_base import HalfDuplexUser

HERE = Path(__file__).resolve().parents[2]
PAGE = Path(__file__).with_name("web.html")
STOP = "###STOP###"
LIMITS = {"max_steps": 100, "max_errors": 10}  # the golden sets' run limits
FIRST = "[mobile_data_issue]user_abroad_roaming_enabled_off[PERSONA:None]"
LOOKUPS = (
    "check_",
    "run_speed_test",
    "can_send_mms",
    "get_",
)  # tool calls that change nothing


class Busy(Exception):
    pass


class HumanState(BaseModel):
    messages: list = []


class Human(HalfDuplexUser):
    """The customer, played on the page: each turn waits for a message or a phone action from it."""

    def __init__(self, tools):
        super().__init__(tools=tools)
        self.actions: queue.Queue = queue.Queue()
        self.waiting = threading.Event()

    def get_init_state(self, message_history=None) -> HumanState:
        return HumanState(messages=list(message_history or []))

    def generate_next_message(self, message, state):
        self.waiting.set()
        action = self.actions.get()
        self.waiting.clear()
        return action, state


def parse_action(text: str) -> tuple[str, dict]:
    """`toggle_roaming()` or `grant_app_permission(app_name="messaging", permission="sms")` as a name and arguments."""
    try:
        node = ast.parse(text.strip(), mode="eval").body
        if (
            not isinstance(node, ast.Call)
            or not isinstance(node.func, ast.Name)
            or node.args
            or any(k.arg is None for k in node.keywords)
        ):
            raise ValueError
        return node.func.id, {k.arg: ast.literal_eval(k.value) for k in node.keywords}
    except (SyntaxError, ValueError):
        raise ValueError(
            f"write a phone action as name(key=value), got {text!r}"
        ) from None


def policy(prompts: dict[str, str]) -> str:
    """tau2's telecom policy composed the way its environment does, from the config's files (as the gate adapter)."""
    return (
        f"<main_policy>\n{prompts['main']}\n</main_policy>\n"
        f"<tech_support_policy>\n{prompts['tech_support']}\n</tech_support_policy>"
    )


def changes(trajectory: list) -> dict:
    """Who changed what: the customer's and the agent's tool calls that succeeded and are not lookups."""
    failed = {m.id for m in trajectory if isinstance(m, ToolMessage) and m.error}
    out = {"customer": [], "agent": [], "agent_lookups": 0}
    for m in trajectory:
        if isinstance(m, ToolMessage):
            continue
        for c in m.tool_calls or []:
            agent = isinstance(m, AssistantMessage)
            if c.name.startswith(LOOKUPS):
                out["agent_lookups"] += agent
            elif c.id not in failed:
                out["agent" if agent else "customer"].append(c.name)
    return out


def events(trajectory: list) -> list[dict]:
    out = []
    for m in trajectory:
        role = "agent" if isinstance(m, AssistantMessage) else "user"
        if isinstance(m, ToolMessage):
            out.append({"role": "result", "for": "agent" if m.requestor == "assistant" else "user",
                        "text": m.content, "error": m.error})  # fmt: skip
            continue
        if m.content and m.content.strip():
            out.append({"role": role, "text": m.content})
        for c in m.tool_calls or []:
            out.append({"role": role, "tool": c.name, "args": c.arguments})
    return out


class Session:
    """One conversation: tau2's orchestrator in a thread, its environment read for the phone and the carrier's line."""

    def __init__(self, version: dict, user: dict, prompts: dict, tasks: dict):
        self.version, self.user, self.prompts, self.tasks = (
            version,
            user,
            prompts,
            tasks,
        )
        self.thread = self.human = None
        self.control = (
            threading.RLock()
        )  # one start or customer action at a time; verdicts land under it too
        self.start(FIRST if FIRST in tasks else next(iter(tasks)), "you")

    @property
    def done(self) -> bool:
        return self.thread is not None and not self.thread.is_alive()

    @property
    def busy(self) -> bool:
        if self.thread is None or not self.thread.is_alive():
            return False
        return self.human is None or not self.human.waiting.is_set()

    def start(self, task_id: str, mode: str) -> None:
        if task_id not in self.tasks:
            raise KeyError(f"no task {task_id}")
        if mode not in ("you", "simulator"):
            raise ValueError("mode is you or simulator")
        with self.control:
            if self.thread is not None and self.thread.is_alive():
                if self.human is None or not self.human.waiting.is_set():
                    raise Busy("the agent is still working")
                self.human.actions.put(
                    UserMessage.text(STOP)
                )  # ends the old chat; its thread finishes on its own
            task = self.tasks[task_id]
            env = build_environment("telecom", solo_mode=False)
            env.policy = policy(self.prompts)
            agent = build_agent("llm_agent", env, llm=self.version["model"], llm_args=dict(self.version["params"]),
                                task=task, solo_mode=False)  # fmt: skip
            if mode == "you":
                self.human = user = Human(env.get_user_tools())
            else:
                self.human = None
                user = build_user("user_simulator", env, task, llm=self.user["model"],
                                  llm_args=dict(self.user.get("params") or {}))  # fmt: skip
            orch = Orchestrator(domain="telecom", agent=agent, user=user, environment=env, task=task, seed=None,
                                solo_mode=False, simulation_id=str(uuid.uuid4()), **LIMITS)  # fmt: skip
            self.task, self.mode, self.env, self.orch = task, mode, env, orch
            self.result = self.error = None
            self.initial_line = None
            self.thread = threading.Thread(
                target=self.run, args=(orch, task), daemon=True
            )
            self.thread.start()
            for _ in range(300):  # until tau2 has set up the phone and the greeting
                if orch.trajectory or not self.thread.is_alive():
                    break
                time.sleep(0.01)
            self.initial_line = self.line()

    def run(self, orch, task) -> None:
        try:
            sim = run_simulation(orch, evaluation_type=EvaluationType.ALL)
        except Exception as e:  # noqa: BLE001 - shown on the page, the server keeps running
            with self.control:
                if orch is self.orch:
                    self.error = f"{type(e).__name__}: {e}"
            return
        info, criteria = sim.reward_info, task.evaluation_criteria
        by = {"assistant": "agent", "user": "customer"}
        # tau2 scores most telecom tasks on the end state only, so the page also says who changed what
        result = {
            "reward": info.reward,
            "termination": sim.termination_reason.value,
            "basis": [getattr(b, "value", str(b)) for b in criteria.reward_basis],
            "assertions": [{"name": a.env_assertion.func_name, "met": bool(a.met)} for a in info.env_assertions or []],
            "actions": [{"name": c.action.name, "by": by.get(c.action.requestor, c.action.requestor),
                         "met": bool(c.action_match)} for c in info.action_checks or []],
            "expected": [{"name": a.name, "by": by.get(a.requestor, a.requestor)} for a in criteria.actions or []],
            "changes": changes(list(orch.trajectory)),
        }  # fmt: skip
        with self.control:
            if orch is self.orch:  # not a chat that was restarted
                self.result = result

    def act(self, message: UserMessage) -> None:
        with self.control:
            if self.human is None or not self.human.waiting.is_set():
                raise Busy(
                    "it is not the customer's turn"
                    if self.human
                    else "the simulator plays the customer"
                )
            self.human.actions.put(message)
            for _ in range(100):  # until the orchestrator has taken it
                if not self.human.waiting.is_set():
                    break
                time.sleep(0.005)

    def say(self, text: str) -> None:
        self.act(UserMessage.text(text))

    def tap(self, name: str, arguments: dict) -> None:
        tools = {t.name for t in self.env.get_user_tools()}
        if name not in tools:
            raise ValueError(f"the phone has no action {name}")
        call = ToolCall(
            id=f"web-{uuid.uuid4().hex[:8]}",
            name=name,
            arguments=arguments,
            requestor="user",
        )
        self.act(UserMessage(role="user", content=None, tool_calls=[call]))

    def phone(self) -> dict:
        db = self.env.user_tools.db
        return {
            "device": db.device.model_dump(mode="json"),
            "surroundings": db.surroundings.model_dump(mode="json"),
            "data_works": self.env.user_tools._get_mobile_data_working(),
        }

    def line(self) -> dict | None:
        number = self.env.user_tools.db.surroundings.phone_number
        db = self.env.tools.db
        line = next((x for x in db.lines if x.phone_number == number), None)
        if line is None:
            return None
        plan = next((p for p in db.plans if p.plan_id == line.plan_id), None)
        customer = next((c for c in db.customers if line.line_id in c.line_ids), None)
        bills = [b for b in db.bills if customer and b.bill_id in customer.bill_ids]
        return {
            "line": line.model_dump(mode="json"),
            "plan": plan.model_dump(mode="json") if plan else None,
            "customer": {"name": customer.full_name, "id": customer.customer_id}
            if customer
            else None,
            "bills": [b.model_dump(mode="json") for b in bills],
        }

    def snapshot(self, since: int = 0) -> dict:
        for _ in range(
            4
        ):  # the orchestrator thread may change the world while it is read
            try:
                return self.read(since)
            except (RuntimeError, ValueError):
                time.sleep(0.01)
        return self.read(since)

    def read(self, since: int) -> dict:
        phone, line, evs = self.phone(), self.line(), events(list(self.orch.trajectory))
        s = self.task.user_scenario.instructions
        return {
            "task": {"id": self.task.id, "reason": s.reason_for_call, "known": s.known_info, "unknown": s.unknown_info,
                     "instructions": s.task_instructions},
            "mode": self.mode,
            "model": self.version["model"],
            "events": evs[since:],
            "count": len(evs),
            "busy": self.busy,
            "your_turn": self.human is not None and self.human.waiting.is_set(),
            "done": self.done,
            "error": self.error,
            "phone": phone,
            "line": line,
            "initial_line": self.initial_line,
            "actions": sorted(t.name for t in self.env.get_user_tools()),
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
            elif url.path == "/api/tasks":
                self.send(200, list(session.tasks))
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
                if path == "/api/start":
                    session.start(body["task"], body.get("mode", "you"))
                elif path == "/api/say":
                    text = str(body.get("text", "")).strip()
                    if not text:
                        raise ValueError("write a message first")
                    session.say(text)
                elif path == "/api/tap":
                    session.tap(*parse_action(str(body.get("action", ""))))
                elif path == "/api/end":
                    session.say(STOP)
                else:
                    return self.send(404, {"error": "not found"})
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
    p.add_argument("--port", type=int, default=8766)
    p.add_argument("--config", type=Path, default=HERE / "configs" / "telecom.yaml")
    a = p.parse_args()
    config = yaml.safe_load(a.config.read_text())
    try:
        prompts = {
            k: (a.config.parent / config["prompt"][k]).read_text()
            for k in ("main", "tech_support")
        }
    except FileNotFoundError as e:
        sys.exit(f"{e}\ntau2's data is missing: run sh fetch_data.sh")
    manifest = yaml.safe_load((HERE / "golden" / "telecom-chat.yaml").read_text())
    every = {t.id: t for t in load_tasks("telecom")}
    tasks = {i: every[i] for i in manifest["tasks"]}
    version = {"model": config["model"], "params": config.get("params") or {}}
    server = serve(Session(version, manifest["user"], prompts, tasks), a.host, a.port)
    print(f"tau2 telecom agent ({version['model']}) at http://{a.host}:{server.server_port}  (Ctrl+C stops it)",
          flush=True)  # fmt: skip
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
