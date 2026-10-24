# Support agent example

A tool-using agent of the kind a product team builds: the support agent of Workbench, a made-up coworking space. Members
ask it to book, move or cancel desks and meeting rooms; it looks things up and changes a mock database through eight
tools, under a written policy. The test cases are this project's own, the way a team writes them from its tickets.

| Path | What |
|---|---|
| `policy.md` | the agent's policy: verification, plans, cancellation credits, escalation |
| `tools.yaml` | the tools the agent sees, with their descriptions |
| `cases/` | `world.yaml`, the starting database; `simulator.yaml`, the member simulator; one file per case |
| `src/support_agent/world.py` | the database in memory and the eight tools |
| `src/support_agent/agent.py` | the agent loop, the simulated member, one run of a case |
| `src/support_agent/run.py` | runs cases against the API and prints what happened |
| `src/support_agent/gate_adapter.py` | the gate's view: `build(config)` and `run(case)`, recording a trace |
| `src/support_agent/golden.py` | builds `golden/solo` and `golden/chat` from `cases/` |
| `configs/support.yaml` | the version under test for the gate |

The version under test is `policy.md`, `tools.yaml`, the agent's model and parameters, its step limit and the agent
code. The member simulator (`cases/simulator.yaml`: model, parameters, guidelines) belongs to the test set with the
cases, so a pull request that changes the agent leaves the member as it was.

## Two modes

- **Alone:** the agent gets the case's `ticket` as one message and cannot ask questions. Only the agent adds noise.
- **Chat** (`--chat`): a model plays the member from the case's `user` scenario and ends the chat with `###STOP###`.
  The simulator adds its own noise, and the difference between the modes estimates how much.

## Cases

Each case gives a time (`now`), a ticket, a member scenario, extra rows for the starting world, the actions a correct
agent takes and the change they make (`expect`). The tests run those actions on a fresh world and check that they make
exactly that change, so a wrong reference fails before any model sees the case.

| Category | Cases |
|---|---|
| happy | `book-desk`, `book-room` |
| policy | `cancel-early`, `cancel-late`, `move-booking` |
| escalation | `cancel-big-credit` |
| refusal | `room-on-basic`, `wrong-name`, `overlap` |
| ambiguous | `which-booking`: in a chat the member does not say which booking until asked; alone, the ticket names it |

The tools enforce only what a booking system would: no double-booked space, opening hours, no past slots. Plans, the
1 to 4 hour length, a member's overlapping bookings, name checks, credits and escalation are policy. The agent can break
them, and the cases check whether it does.

## Running

Run the commands from this directory, with `OPENAI_API_KEY` in `../../.env`.

```sh
uv sync
uv run pytest
# the agent alone on two cases
uv run --env-file ../../.env python -m support_agent.run cases/cancel-late.yaml cases/overlap.yaml \
  --model gpt-5.4-mini-2026-03-17 --params '{"temperature": 0}'
# in a chat with a simulated member
uv run --env-file ../../.env python -m support_agent.run cases/which-booking.yaml --chat \
  --model gpt-5.4-mini-2026-03-17 --params '{"temperature": 0}'
```

Each run prints the agent's tool calls and replies, the change it made to the database, the expected change, and
whether they match. `--out runs.jsonl` keeps one line per run with the time, the hashes of `policy.md`, `tools.yaml` and
`simulator.yaml`, and the model the API reports.

The database comparison sees only the end state. An agent that skips the name check, or one whose simulated member did
the work, can still match it; checks on the agent's own steps come with the gate's trace.

## Under the gate

`configs/support.yaml` is the version under test: the agent's model, `policy.md` and `tools.yaml`. Its hash changes when
any of them does. `golden/solo` and `golden/chat` are the test sets, built from `cases/` (`python -m support_agent.golden`;
a test checks they match). A chat case lists `cases/simulator.yaml` as an input, so the simulator belongs to the set's
hash, not to the version.

Each golden case passes only if every check does (`aggregate: all`): the database changed as the reference actions
change it, the agent called a tool itself, it looked the member up before any write, it issued no credit above €30,
and it used at most 15 model calls.

```sh
# 3 runs per case, alone on the ticket
uv run --env-file ../../.env python -m llm_release_gate.runner --config configs/support.yaml \
  --golden golden/solo -k 3 --out ../../data/runs/support-solo.jsonl --prices prices.yaml
```

The adapter wraps the model client and the world's tool function (`llm_release_gate.trace`), so every record holds the
run's steps: who called which tool with which arguments, the model calls of the agent and of the simulated member with
their tokens and cost, and the change to the database. The application code does not import the gate.
