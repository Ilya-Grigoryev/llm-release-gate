"""The support agent under the gate: name `support_agent.gate_adapter` in `pipeline:` of a gate config.

The adapter records the run without the application knowing: the model client and the world's tool function are
wrapped (`llm_release_gate.trace`). A case with a `simulator` input runs as a chat with the simulated member, one
without runs alone on the ticket; the golden set decides, so the simulator stays part of the test set.
"""

import time

import openai
import yaml
from openai import OpenAI

from llm_release_gate import trace
from llm_release_gate.pipeline import Answer, Case, Fatal, PipelineConfig, Retryable
from support_agent import agent
from support_agent.cases import load_case
from support_agent.world import diff, tool_specs

VERSION = 1  # bump when the agent code changes what the model gets
MAX_STEPS = 20


class Adapter:
    def __init__(self, config: PipelineConfig, client: OpenAI):
        if not isinstance(config.prompt, dict) or set(config.prompt) != {
            "policy",
            "tools",
        }:
            raise ValueError("prompt must name two files: policy and tools")
        self.config = config
        self.policy = config.prompt["policy"].read_text()
        self.tools = tool_specs(config.prompt["tools"])
        self.agent_client = trace.openai_client(client, actor="agent")
        self.user_client = trace.openai_client(client, actor="user")

    def run(self, case: Case) -> Answer:
        support = load_case(case.inputs["case"])
        world = support.world()
        before = world.state()
        world.call = trace.wrap_tool(world.call)
        user = None
        if "simulator" in case.inputs:
            sim = yaml.safe_load(case.inputs["simulator"].read_text())
            user = {"client": self.user_client, **sim}
        start = time.perf_counter()
        try:
            t = agent.run(
                support,
                world,
                client=self.agent_client,
                model=self.config.model,
                params=self.config.params,
                policy=self.policy,
                tools=self.tools,
                user=user,
                max_steps=MAX_STEPS,
            )
        except openai.RateLimitError as e:
            if getattr(e, "code", None) == "insufficient_quota":
                raise Fatal(str(e)) from e
            raise Retryable(str(e)) from e
        except (openai.APIConnectionError, openai.InternalServerError) as e:
            raise Retryable(str(e)) from e
        except (
            openai.AuthenticationError,
            openai.PermissionDeniedError,
            openai.NotFoundError,
        ) as e:
            raise Fatal(str(e)) from e  # wrong key or model: every other call fails too
        change = diff(before, world.state())
        current = trace.current()
        if current is not None:
            current.final_state = world.state()
            current.state_change = change
            current.stop = t.stop
        replies = [e["text"] for e in t.events if e["role"] == "agent" and "text" in e]
        reply = replies[-1] if replies else ""
        return Answer(
            output={"reply": reply, "stop": t.stop, "state_change": change},
            raw=reply,
            input_tokens=t.tokens["agent"][0],
            output_tokens=t.tokens["agent"][1],
            latency_s=round(time.perf_counter() - start, 3),
            model=t.model.get("agent", self.config.model),
        )


def client_for(config: PipelineConfig) -> OpenAI:
    # The runner retries and counts retries, so the SDK must not retry on its own.
    try:
        return OpenAI(max_retries=0, timeout=config.timeout_s)
    except openai.OpenAIError as e:  # no OPENAI_API_KEY: a config error, not a crash
        raise ValueError(str(e)) from e


def build(config: PipelineConfig, client: OpenAI | None = None) -> Adapter:
    return Adapter(config, client or client_for(config))
