# llm-release-gate

A CI gate for LLM pipelines. On every merge request it runs the base and the candidate version of a pipeline over a fixed test set and blocks the merge if:

- quality dropped by more than an agreed margin, with enough evidence to rule out run-to-run noise;
- cost went over budget;
- latency went over budget.

The gate runs each case several times and compares the two versions case by case, so shared difficulty cancels out.

## Status

Work in progress. The gate does not exist yet. Two pipelines under test extract company, address, date and total from receipts in [SROIE](https://rrc.cvc.uab.es/?ch=13) (ICDAR 2019): one reads the OCR text, the other reads the scan.

## Running the pipeline

You need the Kaggle copy of SROIE in `data/SROIE2019/` (`train/` and `test/`, each with `img/`, `box/` and `entities/`) and `OPENAI_API_KEY` in `.env`.

Each pipeline version is a YAML file in `configs/`: model snapshot, prompt file, input (`text` or `image`) and API parameters.

```sh
# OCR text as input
uv run --env-file .env python -m llm_release_gate.pipelines.sroie
# the scan as input
uv run --env-file .env python -m llm_release_gate.pipelines.sroie --config configs/sroie-image.yaml
```

The pipeline prints expected and extracted fields for the first ten training receipts and appends one JSON line per call to `data/runs/sroie.jsonl`. `--help` lists the options.

To add a pipeline, write a module in `src/llm_release_gate/pipelines/` with a `build(config)` function and put its name in `pipeline:` of the config. Gate code loads the module by that name and does not import pipeline modules.

## Golden set

Each case is a YAML file with its inputs next to it; `src/llm_release_gate/case.schema.json` defines the format. The SROIE set lives in `data/golden/sroie/` and stays out of git. `golden/sroie.yaml` records the seed, the receipt ids and the set hash.

```sh
# rebuild the set from the ids in golden/sroie.yaml
uv run python -m llm_release_gate.pipelines.sroie_golden
uv run python -m llm_release_gate.golden validate data/golden/sroie --manifest golden/sroie.yaml
```

Without a manifest the generator samples 30 training receipts with seed 0, leaving out the first 10, and writes a new one.

`validate` checks the schema, unique ids and that every input exists inside the set, then prints a sha256 over the parsed cases and the input bytes. Reformatting a case keeps the hash. Editing an expectation or an input changes it. With `--manifest` it also fails unless the ids and the hash match.

## Context

Bachelor thesis at the University of Vienna, Software Architecture group. Supervisor: Dr. Theodoros Theodoropoulos.
