# Support agent example

A tool-using agent of the kind a product team builds: the support agent of Workbench, a made-up coworking space. Members
ask it to book, move or cancel desks and meeting rooms; it looks things up and changes a mock database through eight
tools, under a written policy. The test cases are this project's own, the way a team writes them from its tickets.

| Path | What |
|---|---|
| `policy.md` | the agent's policy: verification, plans, cancellation credits, escalation |
| `tools.yaml` | the tools the agent sees, with their descriptions |
| `simulator.md` | guidelines for the model that plays the member |
| `cases/` | `world.yaml`, the starting database, and one file per case |
| `src/support_agent/world.py` | the database in memory and the eight tools |
| `src/support_agent/agent.py` | the agent loop, the simulated member, one run of a case |
| `src/support_agent/run.py` | runs cases against the API and prints what happened |

`policy.md` and `tools.yaml` are the version under test: a pull request that edits them changes the agent. The member
simulator (`simulator.md`, its model and parameters) belongs to the test set, so a change to the agent never changes the
member it talks to.

## Two modes

- **Alone:** the agent gets the case's `ticket` as one message and cannot ask questions. Only the agent adds noise.
- **Chat:** a model plays the member from the case's `user` scenario and ends the chat with `###STOP###`. The simulator
  adds its own noise, and the difference between the modes estimates how much.

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
| ambiguous | `which-booking` (the member does not say which booking until asked) |

The tools enforce only what a booking system would: no double-booked space, opening hours, no past slots. Plans, a
member's overlapping bookings, credits and escalation are policy. The agent can break them, and the cases check
whether it does.

## Running

Run the commands from this directory, with `OPENAI_API_KEY` in `../../.env`.

```sh
uv sync
uv run pytest
# the agent alone on two cases
uv run --env-file ../../.env python -m support_agent.run cases/cancel-late.yaml cases/overlap.yaml \
  --model gpt-5.4-mini-2026-03-17 --params '{"temperature": 0}'
# in a chat with a simulated member
uv run --env-file ../../.env python -m support_agent.run cases/which-booking.yaml \
  --model gpt-5.4-mini-2026-03-17 --params '{"temperature": 0}' \
  --user-model gpt-5.4-mini-2026-03-17 --user-params '{"temperature": 0}'
```

Each run prints the agent's tool calls and replies, the change it made to the database, the expected change, and
whether they match.
