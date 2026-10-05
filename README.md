# llm-release-gate

A CI gate for LLM pipelines. On every merge request it runs the base and the candidate version of a pipeline over a fixed test set and blocks the merge if:

- quality dropped by more than an agreed margin, with enough evidence to rule out run-to-run noise;
- cost went over budget;
- latency went over budget.

The gate runs each case several times and compares the two versions case by case, so shared difficulty cancels out.

## Status

Work in progress, no code yet. The first pipeline under test extracts company, address, date and total from scanned receipts in [SROIE](https://rrc.cvc.uab.es/?ch=13) (ICDAR 2019).

## Context

Bachelor thesis at the University of Vienna, Software Architecture group. Supervisor: Dr. Theodoros Theodoropoulos.
