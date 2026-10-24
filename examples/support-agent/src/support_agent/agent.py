"""The support agent: an OpenAI tool-calling loop over the world, alone on a ticket or in a chat with a simulated member."""

import json
from dataclasses import dataclass, field

from support_agent.cases import SupportCase
from support_agent.world import ToolError, World

GREETING = "Hi! How can I help you today?"
SOLO = (
    "\n\n## This conversation\n\nYou are working on a written ticket. The member is not in the chat, so you cannot ask"
    " questions or get confirmations: act on the ticket as written, then reply with a short summary of what you did."
)
STOP = "###STOP###"


@dataclass
class Transcript:
    events: list = field(default_factory=list)  # who did what, in order
    stop: str = ""  # done (solo), user_stop, max_steps or max_turns
    tokens: dict = field(
        default_factory=lambda: {"agent": [0, 0], "user": [0, 0]}
    )  # [input, output]
    model: dict = field(default_factory=dict)  # the model each side reported

    def count(self, side: str, response) -> None:
        self.tokens[side][0] += response.usage.prompt_tokens
        self.tokens[side][1] += response.usage.completion_tokens
        self.model[side] = response.model


class Agent:
    def __init__(
        self,
        client,
        model: str,
        params: dict,
        system: str,
        tools: list,
        world: World,
        transcript: Transcript,
        max_steps: int,
    ):
        self.client, self.model, self.params, self.tools = client, model, params, tools
        self.world, self.transcript, self.max_steps = world, transcript, max_steps
        now = f"{world.now:%A %Y-%m-%d %H:%M}"
        self.messages = [
            {"role": "system", "content": f"{system}\n\nCurrent time: {now}."}
        ]
        self.steps = 0  # model calls

    def respond(self, text: str) -> str | None:
        """Take the member's message and call tools until the model answers in words; None at the step limit."""
        self.messages.append({"role": "user", "content": text})
        while self.steps < self.max_steps:
            self.steps += 1
            r = self.client.chat.completions.create(
                model=self.model,
                messages=self.messages,
                tools=self.tools,
                **self.params,
            )
            self.transcript.count("agent", r)
            message = r.choices[0].message
            calls = message.tool_calls or []
            self.messages.append(
                {
                    "role": "assistant",
                    "content": message.content,
                    **({"tool_calls": [call_dict(c) for c in calls]} if calls else {}),
                }
            )
            if not calls:
                reply = message.content or ""
                self.transcript.events.append({"role": "agent", "text": reply})
                return reply
            for call in calls:
                self.messages.append(
                    {"role": "tool", "tool_call_id": call.id, "content": self.use(call)}
                )
        return None

    def use(self, call) -> str:
        """Run one tool call on the world; a refusal goes back to the model as an error."""
        event = {"role": "agent", "tool": call.function.name}
        try:
            args = json.loads(call.function.arguments or "{}")
            event["args"] = args
            event["result"] = self.world.call(call.function.name, args)
        except (json.JSONDecodeError, ToolError) as e:
            event["error"] = str(e)
        self.transcript.events.append(event)
        return json.dumps(
            {"error": event["error"]} if "error" in event else event["result"]
        )


def call_dict(call) -> dict:
    return {
        "id": call.id,
        "type": "function",
        "function": {"name": call.function.name, "arguments": call.function.arguments},
    }


class Simulator:
    """The member, played by a model. Its model, parameters and guidelines belong to the test set, not to the agent."""

    def __init__(
        self,
        client,
        model: str,
        params: dict,
        guidelines: str,
        user: dict,
        transcript: Transcript,
    ):
        self.client, self.model, self.params, self.transcript = (
            client,
            model,
            params,
            transcript,
        )
        scenario = f"{user['known'].strip()}\n\n{user['instructions'].strip()}"
        self.messages = [
            {
                "role": "system",
                "content": f"{guidelines}\n\n## Your scenario\n\n{scenario}",
            }
        ]

    def respond(self, text: str) -> str:
        self.messages.append(
            {"role": "user", "content": text}
        )  # the agent speaks as `user` here
        r = self.client.chat.completions.create(
            model=self.model, messages=self.messages, **self.params
        )
        self.transcript.count("user", r)
        reply = r.choices[0].message.content or ""
        self.messages.append({"role": "assistant", "content": reply})
        self.transcript.events.append({"role": "user", "text": reply})
        return reply


def run(
    case: SupportCase,
    world: World,
    *,
    client,
    model: str,
    params: dict,
    policy: str,
    tools: list,
    user: dict | None = None,
    max_steps: int = 20,
    max_turns: int = 10,
) -> Transcript:
    """One run of a case. Without `user` the agent works alone on the ticket; with it, a simulated member chats.

    `user` holds the simulator's `client`, `model`, `params` and `guidelines`.
    """
    transcript = Transcript()
    if user is None:
        agent = Agent(
            client, model, params, policy + SOLO, tools, world, transcript, max_steps
        )
        transcript.stop = (
            "done" if agent.respond(case.ticket) is not None else "max_steps"
        )
        return transcript
    agent = Agent(client, model, params, policy, tools, world, transcript, max_steps)
    member = Simulator(
        user["client"],
        user["model"],
        user["params"],
        user["guidelines"],
        case.user,
        transcript,
    )
    agent.messages.append({"role": "assistant", "content": GREETING})
    transcript.events.append({"role": "agent", "text": GREETING})
    said = GREETING
    for _ in range(max_turns):
        heard = member.respond(said)
        if STOP in heard:
            transcript.stop = "user_stop"
            return transcript
        said = agent.respond(heard)
        if said is None:
            transcript.stop = "max_steps"
            return transcript
    transcript.stop = "max_turns"
    return transcript
