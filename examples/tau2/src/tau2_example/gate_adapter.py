"""tau2-bench v1.0.1 under the gate: name `tau2_example.gate_adapter` in `pipeline:` of a gate config.

tau2's own agent, user simulator, environment and evaluator run each case; the adapter swaps in the policy from the
config (so it is part of the version and its hash), takes the simulator from the golden set (so it is part of the set
and its hash) and turns tau2's messages into the gate's trace. tau2's evaluator needs the simulated phone and database,
so it runs here; the gate's checks read its verdicts from the answer.
"""

import hashlib
import importlib.metadata
import json
import time
from pathlib import Path
from typing import Any

import litellm
import yaml
from tau2.data_model.tasks import Task
from tau2.domains.telecom.utils import TELECOM_DB_PATH, TELECOM_USER_DB_PATH
from tau2.evaluator.evaluator import EvaluationType
from tau2.orchestrator.orchestrator import Orchestrator
from tau2.runner import (
    build_agent,
    build_environment,
    build_user,
    run_simulation,
)
from tau2.user.user_simulator import (
    GLOBAL_USER_SIM_GUIDELINES_PATH_TOOLS,
    DummyUser,
)

from llm_release_gate import trace
from llm_release_gate.pipeline import Answer, Case, Fatal, PipelineConfig, Retryable
from llm_release_gate.prices import usd

VERSION = 1  # bump when the adapter changes what the models get
TAU2 = importlib.metadata.version("tau2")
RETRY = (
    litellm.RateLimitError,
    litellm.APIConnectionError,
    litellm.InternalServerError,
    litellm.ServiceUnavailableError,
    litellm.Timeout,
)
STOP = (
    litellm.AuthenticationError,
    litellm.PermissionDeniedError,
    litellm.NotFoundError,
)
# tau2's files a case depends on besides its task: the starting world, the simulator's guidelines
PINNED = {
    "db": TELECOM_DB_PATH,
    "user_db": TELECOM_USER_DB_PATH,
    "user_guidelines": GLOBAL_USER_SIM_GUIDELINES_PATH_TOOLS,
}
TOKENS = (
    "###STOP###",
    "###TRANSFER###",
    "###OUT-OF-SCOPE###",
)  # how the simulated user ends a chat


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Adapter:
    def __init__(self, config: PipelineConfig):
        if not isinstance(config.prompt, dict) or set(config.prompt) != {
            "main",
            "main_solo",
            "tech_support",
        }:
            raise ValueError(
                "prompt must name three files: main, main_solo and tech_support"
            )
        self.config = config
        self.prompts = {k: p.read_text() for k, p in config.prompt.items()}

    def policy(self, solo: bool) -> str:
        """Composed the way tau2's telecom environment composes its own (`domains/telecom/environment.py`)."""
        main = self.prompts["main_solo" if solo else "main"]
        return (
            f"<main_policy>\n{main}\n</main_policy>\n"
            f"<tech_support_policy>\n{self.prompts['tech_support']}\n</tech_support_policy>"
        )

    def run(self, case: Case) -> Answer:
        task = Task.model_validate_json(case.inputs["task"].read_text())
        harness = yaml.safe_load(case.inputs["run"].read_text())
        if harness["tau2"] != TAU2:
            raise Fatal(
                f"the golden set is for tau2 {harness['tau2']}, installed is {TAU2}"
            )
        user = harness.get("user")  # none: the agent works the ticket alone
        solo = user is None
        for name, digest in harness["pinned"].items():
            if sha256(PINNED[name]) != digest:
                raise Fatal(f"{PINNED[name]} differs from the golden set's")
        no_retry = {"num_retries": 0}  # the runner retries and counts retries
        env = build_environment(harness["domain"], solo_mode=solo)
        env.policy = self.policy(solo)
        agent = build_agent(
            "llm_agent_solo" if solo else "llm_agent",
            env,
            llm=self.config.model,
            llm_args={**self.config.params, **no_retry},
            task=task,
            solo_mode=solo,
        )
        if solo:  # v1.0.1's build_user passes DummyUser arguments it does not take
            simulator = DummyUser()
        else:
            simulator = build_user(
                "user_simulator",
                env,
                task,
                llm=user["model"],
                llm_args={**user.get("params", {}), **no_retry},
            )
        orchestrator = Orchestrator(
            domain=harness["domain"],
            agent=agent,
            user=simulator,
            environment=env,
            task=task,
            max_steps=harness["max_steps"],
            max_errors=harness["max_errors"],
            seed=harness["seed"],  # None: no seed reaches the provider
            solo_mode=solo,
            simulation_id=case.id,
        )
        start = time.perf_counter()
        try:
            sim = run_simulation(orchestrator, evaluation_type=EvaluationType.ALL)
        except Exception as e:
            record(
                orchestrator.trajectory, self.config.model, user and user["model"]
            )  # paid steps stay
            if isinstance(e, litellm.RateLimitError) and "insufficient_quota" in str(e):
                raise Fatal(str(e)) from e
            if isinstance(e, RETRY):
                raise Retryable(str(e)) from e
            if isinstance(e, STOP):
                raise Fatal(str(e)) from e
            raise
        steps = record(sim.messages, self.config.model, user and user["model"])
        info = sim.reward_info
        stop = sim.termination_reason.value
        if (t := trace.current()) is not None:
            t.stop = {
                "agent_stop": "done",
                "user_stop": "user_stop",
                "max_steps": "max_steps",
            }.get(stop, "error")
        agent_llm = [s for s in steps if s["kind"] == "llm" and s["actor"] == "agent"]
        texts = [s["text"] for s in agent_llm if s.get("text")]
        user_llm = [s for s in steps if s["kind"] == "llm" and s["actor"] == "user"]
        user_said = (user_llm[-1].get("text") or "") if user_llm else ""
        return Answer(
            output={
                "reward": info.reward,
                "assertions": {
                    f"{i}-{a.env_assertion.func_name}": int(a.met)
                    for i, a in enumerate(info.env_assertions or [])
                },
                "termination": stop,
                "user_token": next((k for k in TOKENS if k in user_said), None),
            },
            raw=texts[-1] if texts else "",
            input_tokens=sum(s["tokens_in"] for s in agent_llm),
            output_tokens=sum(s["tokens_out"] for s in agent_llm),
            latency_s=round(time.perf_counter() - start, 3),
            model=next(
                (s["model"] for s in reversed(agent_llm) if s.get("reported")), None
            ),
        )


def parse(text: str | None) -> Any:
    try:
        return json.loads(text) if text else text
    except json.JSONDecodeError:
        return text


def record(messages: list, agent_model: str, user_model: str | None) -> list[dict]:
    """tau2's messages as trace steps (the manual path): model turns, tool calls and their actor, scripted turns.

    Returns the steps also when no trace is current, so the answer can sum the agent's tokens.
    """
    t = trace.current()
    prices = t.prices if t is not None else {}
    asked: dict[
        str, dict
    ] = {}  # tool call id -> name and arguments, to fill the tool steps
    steps = []
    for message in messages:
        for m in getattr(message, "tool_messages", None) or [message]:
            role = m.role.value if hasattr(m.role, "value") else m.role
            if role == "system":
                continue
            actor = "agent" if role == "assistant" else "user"
            if role == "tool":
                call = asked.get(m.id, {})
                step = {
                    "kind": "tool",
                    "actor": "agent" if m.requestor == "assistant" else "user",
                    "ts": m.timestamp,
                    "call_id": m.id,
                    "name": call.get("name"),
                    "args": call.get("args", {}),
                    "status": "error" if m.error else "ok",
                    "result": parse(m.content),
                }
            elif (
                m.usage is None
            ):  # no model behind it: the fixed greeting, the dummy user
                step = {
                    "kind": "message",
                    "actor": actor,
                    "ts": m.timestamp,
                    "text": m.content,
                }
            else:
                raw = m.raw_data or {}
                cached = (
                    (raw.get("usage") or {}).get("prompt_tokens_details") or {}
                ).get("cached_tokens") or 0
                model = raw.get("model") or (
                    agent_model if actor == "agent" else user_model
                )
                calls = [
                    {"id": c.id, "name": c.name, "args": c.arguments}
                    for c in m.tool_calls or []
                ]
                asked.update({c["id"]: c for c in calls})
                step = {
                    "kind": "llm",
                    "actor": actor,
                    "ts": m.timestamp,
                    "status": "ok",
                    "model": model,
                    "reported": bool(raw.get("model")),
                    "tokens_in": m.usage["prompt_tokens"],
                    "tokens_out": m.usage["completion_tokens"],
                    "tokens_cached": cached,
                    "cost_usd": usd(
                        model,
                        m.usage["prompt_tokens"],
                        m.usage["completion_tokens"],
                        prices,
                        cached,
                    ),
                    "finish_reason": ((raw.get("choices") or [{}])[0]).get(
                        "finish_reason"
                    ),
                    "fingerprint": raw.get("system_fingerprint"),
                    "request_id": raw.get("id"),
                    "latency_ms": round(1000 * m.generation_time_seconds)
                    if m.generation_time_seconds
                    else None,
                    "text": m.content,
                    "tool_calls": calls,
                }
            steps.append(step)
            if t is not None:
                fields = {
                    k: v
                    for k, v in step.items()
                    if k not in ("kind", "actor", "reported")
                }
                t.step(step["kind"], step["actor"], **fields)
    return steps


def build(config: PipelineConfig) -> Adapter:
    return Adapter(config)
