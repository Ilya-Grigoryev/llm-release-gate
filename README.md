# llm-release-gate

A CI gate for LLM pipelines. On every merge request it runs the base and the candidate version of a pipeline over a fixed test set and blocks the merge if:

- quality dropped by more than an agreed margin, with enough evidence to rule out run-to-run noise;
- cost went over budget;
- latency went over budget.

The gate runs each case several times and compares the two versions case by case, so shared difficulty cancels out.

## Status

Work in progress. The naive gate works: it compares one run per version against a fixed threshold. The statistical rule, the cost and latency budgets and the merge request job come next. [`examples/sroie/`](examples/sroie/) holds the pipeline under test: it extracts company, address, date and total from receipts in [SROIE](https://rrc.cvc.uab.es/?ch=13) (ICDAR 2019), from the OCR text or from the scan.

## Your pipeline

The gate runs any Python module with a `build(config)` function. `build` returns an object whose `run(case)` gives back an `Answer` (`src/llm_release_gate/pipeline.py`): the parsed output, the raw text, tokens, latency and the model the provider reported. Raise `Retryable` when the same call may succeed later (rate limit, timeout) and `Fatal` when no call can (out of quota, wrong key).

Name the module by its import path in the config of each version:

```yaml
pipeline: my_app.gate_adapter   # installed, or importable from where you run the gate
model: gpt-4.1-mini-2025-04-14  # a dated snapshot
prompt: prompts/extract.md      # relative to this file, or named files: {extract: a.md, check: b.md}
input: text
params: {temperature: 0}
```

The gate's code imports no pipeline. Give your module a `VERSION` and bump it when your code changes what the model gets. [`examples/sroie/`](examples/sroie/) is a whole project set up this way.

## Running a version

Each pipeline version is a YAML file: pipeline module, model snapshot, prompt file (or named prompt files for a pipeline with several steps), input, API parameters and, optionally, `max_retries` (default 5) and `timeout_s` (default 60). Its hash covers every field, the bytes of each prompt and the module's `VERSION`; key order, YAML formatting and `0` versus `0.0` do not change it.

The runner calls the pipeline K times per case of a golden set and appends one JSON record per call, stamped with the config hash, the set hash and the scorer version. A rerun pays only for what is missing. The runner retries rate limits, timeouts and server errors with backoff 1, 2, 4... s and stops when the account is out of quota.

```sh
# from examples/sroie: the scan on the SROIE golden set, 3 runs per receipt
uv run --env-file ../../.env python -m llm_release_gate.runner --config configs/sroie-image.yaml --golden ../../data/golden/sroie -k 3 --out ../../data/runs/image.jsonl
```

## The naive gate

The first gate compares one run per version: it blocks when the candidate's mean score is lower than the base's by more than a threshold, 5 points by default (`--relative` reads it as a percentage of the base mean). It pairs the two files case by case and refuses files with different set hashes, different scorer versions or cases missing from one side. `--golden` rescores both sides from their saved answers with the current scorer, without calling the model.

```sh
uv run python -m llm_release_gate.gate --base data/runs/base.jsonl --candidate data/runs/candidate.jsonl --markdown comment.md --json verdict.json
```

| Exit code | Meaning |
|---|---|
| 0 | pass |
| 10 | quality fail |
| 11 | inconclusive (not produced by the naive gate) |
| 12 | budget fail (not yet checked) |
| 20 | infra error: the runs cannot be compared, or the tool failed |

Python and argparse keep 1 and 2, so a crash is never read as a verdict.

## Golden set

Each case is a YAML file with its inputs next to it; `src/llm_release_gate/case.schema.json` defines the format.

```sh
uv run python -m llm_release_gate.golden validate tests/fixtures/golden
```

`validate` checks the schema, unique ids and that every input exists inside the set, then prints a sha256 over the parsed cases and the input bytes. Reformatting a case keeps the hash. Editing an expectation or an input changes it. With `--manifest` it also fails unless the ids and the hash match. The SROIE set stays out of git; [`examples/sroie/`](examples/sroie/) rebuilds it from a manifest of receipt ids.

## Scoring

A case's `scoring` block picks the scorer. `field_match` compares each expected field with the answer. `fields` gives a field a type: a `date` or a `number` is compared by value (`25/12/2018` matches `25/12/2018 8:13 PM`, `9.00` matches `RM 9.0`), a `string` as text after the listed normalisers (`whitespace`, `casefold`). A label that does not parse is compared as text. A field expected as `null` is not scored. The case score is the share of right fields among the scored ones. Records keep the scorer version, and runs scored by different versions are not compared.

## CI

`.gitlab-ci.yml` and `.github/workflows/ci.yml` run the same checks: lint, the tests of the gate and of the example, and a validation of the test golden set. A manual `model-call` job makes one paid call and needs `OPENAI_API_KEY` as a GitLab CI/CD variable or a GitHub secret.

## Context

Bachelor thesis at the University of Vienna, Software Architecture group. Supervisor: Dr. Theodoros Theodoropoulos.
