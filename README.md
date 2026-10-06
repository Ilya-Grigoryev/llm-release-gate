# llm-release-gate

A CI gate for LLM pipelines. On every merge request it runs the base and the candidate version of a pipeline over a fixed test set and blocks the merge if:

- quality dropped by more than an agreed margin, with enough evidence to rule out run-to-run noise;
- cost went over budget;
- latency went over budget.

The gate runs each case several times and compares the two versions case by case, so shared difficulty cancels out.

## Status

Work in progress. The gate does not exist yet, only the first pipeline under test: it extracts company, address, date and total from scanned receipts in [SROIE](https://rrc.cvc.uab.es/?ch=13) (ICDAR 2019).

## Running the pipeline

You need the Kaggle copy of SROIE in `data/SROIE2019/` (`train/` and `test/`, each with `img/`, `box/` and `entities/`) and `OPENAI_API_KEY` in `.env`.

```sh
# OCR text as input
uv run --env-file .env python -m llm_release_gate.pipelines.sroie
# the scan as input
uv run --env-file .env python -m llm_release_gate.pipelines.sroie --input image --prompt prompts/sroie_image.md
```

The pipeline prints expected and extracted fields for the first ten training receipts and appends one JSON line per call to `data/runs/sroie.jsonl`. `--help` lists the options.

## Context

Bachelor thesis at the University of Vienna, Software Architecture group. Supervisor: Dr. Theodoros Theodoropoulos.
