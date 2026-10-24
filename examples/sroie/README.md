# SROIE example

A pipeline under the gate, set up the way another project would use it: it installs `llm-release-gate` as a dependency and names its own module in `pipeline:`. It extracts company, date, address and total from receipts in [SROIE](https://rrc.cvc.uab.es/?ch=13) (ICDAR 2019), from the OCR text (`configs/sroie-text.yaml`) or from the scan (`configs/sroie-image.yaml`).

| Path | What |
|---|---|
| `src/sroie_example/pipeline.py` | `build(config)`: one OpenAI call per receipt, a JSON schema with the four fields |
| `src/sroie_example/steps.py` | the same in two calls: extract the fields, then check them against the receipt |
| `src/sroie_example/golden.py` | builds the golden set from a SROIE split |
| `src/sroie_example/rescore.py` | rescores saved runs without calling the model |
| `golden/sroie.yaml` | seed, receipt ids and hash of the golden set |

## Setup

Run the commands from this directory. The data stays out of git, in the repository's `data/`: put the Kaggle copy of SROIE in `../../data/SROIE2019/` (`train/` and `test/`, each with `img/`, `box/` and `entities/`) and `OPENAI_API_KEY` in `../../.env`.

```sh
uv sync
# rebuild the golden set from the ids in golden/sroie.yaml, into an empty ../../data/golden/sroie
uv run python -m sroie_example.golden
uv run python -m llm_release_gate.golden validate ../../data/golden/sroie --manifest golden/sroie.yaml
```

Without a manifest the generator samples 30 training receipts with seed 0, leaving out the first 10, and writes a new one.

## Running

```sh
# the scan, 3 runs per receipt
uv run --env-file ../../.env python -m llm_release_gate.runner --config configs/sroie-image.yaml --golden ../../data/golden/sroie -k 3 --out ../../data/runs/image.jsonl
# rescore saved runs: --variant typed (default), text (whitespace and case only) or strict (exact strings, the ICDAR rule)
uv run python -m sroie_example.rescore ../../data/runs/2026-10-12/base-text-r*.jsonl
uv run pytest
```

## One step or two

`configs/sroie-steps.yaml` runs `sroie_example.steps`. Step 1 extracts the fields with the prompt of `sroie-text.yaml`; step 2 gets the receipt and those fields and checks them with `prompts/sroie_check.md`. A record holds the final answer and the tokens and time of both calls. To see whether the second call pays off, run both versions on the same set and let the gate compare them:

```sh
uv run --env-file ../../.env python -m llm_release_gate.runner --config configs/sroie-text.yaml --golden ../../data/golden/sroie --out ../../data/runs/one-step.jsonl
uv run --env-file ../../.env python -m llm_release_gate.runner --config configs/sroie-steps.yaml --golden ../../data/golden/sroie --out ../../data/runs/two-steps.jsonl
uv run python -m llm_release_gate.gate --base ../../data/runs/one-step.jsonl --candidate ../../data/runs/two-steps.jsonl
```

Step 2 also asks for DD/MM/YYYY dates and totals with two decimals; the gate compares dates and amounts by value, so the format alone does not move the score. If step 2 returns no JSON, the case scores 0 even when step 1 was right. A retry repeats both calls, and the record counts the tokens of the last attempt only. The gate sees only the final answer for now: it cannot yet tell which step went wrong.

An edit to a prompt in `prompts/` makes a new pipeline version with its own config hash. Bump `VERSION` in `pipeline.py` when you change what the code sends to the model; the two-step version includes it. In `steps.py`, bump the second number when you change what that file sends in either call.

Pull requests on GitHub and merge requests on GitLab run `release-gate` on this example: see the CI section in the main README.
