# tau2-bench telecom example

The telecom domain of [tau2-bench](https://github.com/sierra-research/tau2-bench) v1.0.1 behind the gate: tau2's own
agent helps a customer fix their phone, with tools on the operator's database while the customer acts on the phone.
tau2's evaluator checks the phone and the database at the end, without an LLM judge. Published success rates exist for
this domain, so it serves as an outside check of the gate next to `examples/support-agent`.

| Path | What |
|---|---|
| `fetch_data.sh` | fetches the tau2 data this example needs (14 MB) into `../../data/tau2-bench`, outside git |
| `src/tau2_example/gate_adapter.py` | `build(config)` and `run(case)`: tau2's agent, simulator and evaluator for one case; tau2's messages become the trace |
| `src/tau2_example/golden.py` | builds a golden set from tau2's tasks and writes or follows a manifest |
| `golden/telecom-solo.yaml`, `golden/telecom-chat.yaml` | the manifests: task ids, sampling, the simulator, the set hash |
| `configs/telecom.yaml`, `configs/telecom-luna.yaml` | the version under test, with `gpt-5.4-mini-2026-03-17` or `gpt-6-luna` |
| `src/tau2_example/pilot_sets.py` | the golden sets of the model pilot (experiment E-005 of the thesis) |

The version under test is the agent's model and parameters and tau2's policy for it (`main_policy.md` or
`main_policy_solo.md` with `tech_support_manual.md`), which the adapter reads from the config, so editing a copy of the
policy changes the version and its hash. The user simulator (model, parameters), tau2's version, the run limits and the
hashes of tau2's starting world (`db.toml`, `user_db.toml`) and simulator guidelines belong to the golden set
(`inputs/run.yaml`), so they change the set's hash instead. The adapter refuses to run when the installed tau2 or any of
those files differ from the set's. No seed reaches the provider, as in the other examples: tau2 would send the same
seed with every call of every repetition.

## Two modes

- **Alone** (`telecom-solo`): tau2's solo agent gets the task's ticket and both tool sets, the customer's included.
- **Chat** (`telecom-chat`): a model plays the customer from the task's scenario and acts on the phone itself.

## Cases and checks

The sets hold the 20 tasks of tau2's `small` split and 10 sampled from `train` (seed 0); `test` stays held out. A case
passes when every check does:

- `reward`: tau2's own verdict (1 or 0). The mean of this check over runs is the success rate tau2 reports.
- `assert-N`: each of the task's environment assertions, the basis of that reward.
- `action-N-<tool>`: the agent called an expected tool with the expected arguments (those in tau2's `compare_args`, or
  all of the action's). Alone, the agent takes every expected action; in a chat, only the operator's, since the customer
  takes the phone's. These are stricter than tau2's reward, which counts the final state only.
- `agent-acted`: the agent called a tool at all. A run where the simulated customer fixed the phone alone does not pass.

The answer also carries tau2's `termination` and `user_token`: how the simulated user ended the chat (`###STOP###`,
`###TRANSFER###`, `###OUT-OF-SCOPE###`), so a simulator that gave up is told apart from an agent that failed.

## Compared with tau2's published numbers

The agent, its policy and the evaluator are tau2's own, the run conditions not quite: the simulator here is the set's
model (`gpt-5.4-mini-2026-03-17`, tau2's default is `gpt-4.1`), the step limit is 100 (tau2's CLI default is 200), no
seed is sent, and `small` is not part of the published `base` split. Read success rates from this example as this
setup's, not as a reproduction.

## Running

Run the commands from this directory, with `OPENAI_API_KEY` in `../../.env`.

```sh
uv sync
sh fetch_data.sh
uv run python -m tau2_example.golden --mode solo   # rebuilds ../../data/golden/tau2-telecom-solo from the manifest
uv run python -m llm_release_gate.golden validate ../../data/golden/tau2-telecom-solo --manifest golden/telecom-solo.yaml
uv run --env-file ../../.env python -m llm_release_gate.runner --config configs/telecom.yaml \
  --golden ../../data/golden/tau2-telecom-solo -k 3 --out ../../data/runs/tau2-solo.jsonl --prices prices.yaml
uv run pytest
```

tau2 retries model calls through litellm by default; the adapter turns that off (`num_retries: 0`), so the runner's
retries are the only ones and are counted. tau2 sets `litellm.drop_params`, which drops `reasoning_effort` for some
models without a word; pass it in `extra_body` (`configs/telecom-luna.yaml`). tau2 needs Python 3.12 (it imports
`audioop`).

tau2-bench is MIT-licensed (Sierra Research); its data stays out of this repository.
