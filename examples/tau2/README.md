# tau2-bench telecom example

The telecom domain of [tau2-bench](https://github.com/sierra-research/tau2-bench) v1.0.1 behind the gate: tau2's own
agent helps a customer fix their phone, with tools on the operator's database while the customer acts on the phone.
tau2's evaluator checks the phone and the database at the end, without an LLM judge. Published success rates exist for
this domain, so it serves as an outside check of the gate next to `examples/support-agent`.

| Path | What |
|---|---|
| `fetch_data.sh` | fetches the tau2 data this example needs (~15 MB) into `../../data/tau2-bench`, outside git |
| `src/tau2_example/gate_adapter.py` | `build(config)` and `run(case)`: tau2's agent, simulator and evaluator for one case; tau2's messages become the trace |
| `src/tau2_example/golden.py` | builds a golden set from tau2's tasks and writes or follows a manifest |
| `golden/telecom-solo.yaml`, `golden/telecom-chat.yaml` | the manifests: task ids, sampling, the simulator, the set hash |
| `configs/telecom.yaml` | the version under test |

The version under test is the agent's model and parameters and tau2's policy for it (`main_policy.md` or
`main_policy_solo.md` with `tech_support_manual.md`), which the adapter reads from the config, so editing a copy of the
policy changes the version and its hash. The user simulator (model, parameters, the hash of tau2's simulator
guidelines), tau2's version and the run limits belong to the golden set (`inputs/run.yaml`), so they change the set's
hash instead. The adapter refuses to run when the installed tau2 or its simulator guidelines differ from the set's.

## Two modes

- **Alone** (`telecom-solo`): tau2's solo agent gets the task's ticket and both tool sets, the customer's included.
- **Chat** (`telecom-chat`): a model plays the customer from the task's scenario and acts on the phone itself.

## Cases and checks

The sets hold the 20 tasks of tau2's `small` split and 10 sampled from `train` (seed 0); `test` stays held out. A case
passes when every check does:

- `reward`: tau2's own verdict (1 or 0). The mean of this check over runs is the success rate tau2 reports.
- `assert-N`: each of the task's environment assertions, the basis of that reward.
- `action-N-<tool>`: the agent called an expected tool with the expected arguments (the ones tau2 compares). Alone, the
  agent takes every expected action; in a chat, only the operator's, since the customer takes the phone's. These are
  stricter than tau2's reward, which counts the final state only.
- `agent-acted`: the agent called a tool at all. A run where the simulated customer fixed the phone alone does not pass.

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
retries are the only ones and are counted. tau2 needs Python 3.12 (it imports `audioop`).

tau2-bench is MIT-licensed (Sierra Research); its data stays out of this repository.
