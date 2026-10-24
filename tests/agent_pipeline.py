"""A tool-using agent outside the gate's package for its tests: a scripted model, a one-row world, no key needed.

The adapter records the way a team's adapter would: the model client and the tool function are wrapped, the
application itself knows nothing about the gate.
"""

import json
from types import SimpleNamespace

from llm_release_gate import trace
from llm_release_gate.pipeline import Answer, Retryable

VERSION = 1


def completion(content=None, calls=(), model="fake-model-2026-01-01", tokens=(100, 10)):
    message = SimpleNamespace(
        content=content,
        tool_calls=[
            SimpleNamespace(
                id=call_id,
                function=SimpleNamespace(name=name, arguments=json.dumps(args)),
            )
            for call_id, name, args in calls
        ]
        or None,
    )
    return SimpleNamespace(
        id="req-1",
        model=model,
        system_fingerprint="fp_1",
        choices=[
            SimpleNamespace(
                message=message, finish_reason="tool_calls" if calls else "stop"
            )
        ],
        usage=SimpleNamespace(prompt_tokens=tokens[0], completion_tokens=tokens[1]),
    )


class ScriptedModel:
    """Stands in for `openai.OpenAI`: answers each call from a script; an exception in the script is raised."""

    def __init__(self, script):
        self.script, self.requests = list(script), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **request):
        self.requests.append(request)
        reply = self.script.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class World:
    def __init__(self):
        self.balance = 0

    def call(self, name, args):
        if name != "add":
            raise ValueError(f"unknown tool {name}")
        self.balance += args["amount"]
        return {"balance": self.balance}


def agent(client, world, request):
    """The application: a plain tool-calling loop."""
    messages = [{"role": "user", "content": request}]
    while True:
        r = client.chat.completions.create(model="fake", messages=messages)
        message = r.choices[0].message
        if not message.tool_calls:
            return message.content
        messages.append({"role": "assistant", "tool_calls": message.tool_calls})
        for c in message.tool_calls:
            try:
                result = world.call(c.function.name, json.loads(c.function.arguments))
            except ValueError as e:
                result = {"error": str(e)}
            messages.append(
                {"role": "tool", "tool_call_id": c.id, "content": json.dumps(result)}
            )


class Adapter:
    """What `build(config)` returns: one scripted model per case id, so the runner can replay it."""

    def __init__(self, scripts):
        self.scripts = scripts

    def run(self, case):
        world = World()
        world.call = trace.wrap_tool(world.call)
        client = trace.openai_client(self.scripts[case.id]())
        try:
            reply = agent(client, world, "add 5")
        except TimeoutError as e:
            raise Retryable(str(e)) from e
        t = trace.current()
        if t is not None:
            t.final_state = {"balance": world.balance}
            t.state_change = {"balance": world.balance}
            t.stop = "done"
        return Answer(
            output={"balance": world.balance},
            raw=reply,
            input_tokens=0,
            output_tokens=0,
            latency_s=0.0,
            model="fake-model-2026-01-01",
        )
