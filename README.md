# llm-release-gate

A CI gate for LLM pipelines. On every merge request it runs the base and the candidate version of a pipeline over a fixed test set and blocks the merge if:

- quality dropped by more than an agreed margin, with enough evidence to rule out run-to-run noise;
- cost went over budget;
- latency went over budget.

The gate runs each case several times and compares the two versions case by case, so shared difficulty cancels out.

## Status

Work in progress. The gate does not exist yet. Two pipelines under test extract company, address, date and total from receipts in [SROIE](https://rrc.cvc.uab.es/?ch=13) (ICDAR 2019): one reads the OCR text, the other reads the scan.

## Running a version

Each pipeline version is a YAML file in `configs/`: model snapshot, prompt file, input (`text` or `image`), API parameters and, optionally, `max_retries` (default 5) and `timeout_s` (default 60). Its hash covers every field and the prompt's bytes; key order, YAML formatting and `0` versus `0.0` do not change it.

The runner calls the pipeline K times per case of a golden set and appends one JSON record per call, stamped with the config hash, the set hash and the scorer version. A rerun pays only for what is missing. Rate limits, timeouts and server errors are retried with backoff 1, 2, 4... s; an account out of quota stops the run. You need `OPENAI_API_KEY` in `.env`.

```sh
# OCR text, the CI fixture, one call
uv run --env-file .env python -m llm_release_gate.runner --config configs/sroie-text.yaml --golden tests/fixtures/golden --out data/runs/try.jsonl
# the scan on the SROIE golden set, 3 runs per receipt
uv run --env-file .env python -m llm_release_gate.runner --config configs/sroie-image.yaml --golden data/golden/sroie -k 3 --out data/runs/image.jsonl
```

`llm_release_gate.compare` pairs two such files case by case and refuses files with different set hashes or scorer versions.

To add a pipeline, write a module in `src/llm_release_gate/pipelines/` with a `build(config)` function and put its name in `pipeline:` of the config. Gate code loads the module by that name and does not import pipeline modules.

## Golden set

The SROIE set needs the Kaggle copy of SROIE in `data/SROIE2019/` (`train/` and `test/`, each with `img/`, `box/` and `entities/`).

Each case is a YAML file with its inputs next to it; `src/llm_release_gate/case.schema.json` defines the format. The SROIE set lives in `data/golden/sroie/` and stays out of git. `golden/sroie.yaml` records the seed, the receipt ids and the set hash.

```sh
# rebuild the set from the ids in golden/sroie.yaml
uv run python -m llm_release_gate.pipelines.sroie_golden
uv run python -m llm_release_gate.golden validate data/golden/sroie --manifest golden/sroie.yaml
```

Without a manifest the generator samples 30 training receipts with seed 0, leaving out the first 10, and writes a new one.

`validate` checks the schema, unique ids and that every input exists inside the set, then prints a sha256 over the parsed cases and the input bytes. Reformatting a case keeps the hash. Editing an expectation or an input changes it. With `--manifest` it also fails unless the ids and the hash match.

## Scoring

A case's `scoring` block picks the scorer. `field_match` compares each expected field with the answer after the listed normalisers (`whitespace`, `casefold`). A field expected as `null` is not scored. The case score is the share of right fields among the scored ones.

```sh
# rescore saved runs without calling the model; needs data/SROIE2019
uv run python -m llm_release_gate.pipelines.sroie_rescore data/runs/2026-10-12/base-text-r*.jsonl
```

## Context

Bachelor thesis at the University of Vienna, Software Architecture group. Supervisor: Dr. Theodoros Theodoropoulos.
