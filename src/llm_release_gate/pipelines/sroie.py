"""SROIE pipeline: receipt OCR text or scan -> LLM -> company, date, address, total."""

import argparse
import base64
import json
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import openai
from openai import OpenAI

from llm_release_gate.metrics import score
from llm_release_gate.pipeline import (
    Answer,
    Case,
    Fatal,
    PipelineConfig,
    Retryable,
    load_config,
)
from llm_release_gate.runner import call

FIELDS = ("company", "date", "address", "total")
INPUTS = ("text", "image")
SCORING = {"method": "field_match", "normalise": ["whitespace", "casefold"]}
SCHEMA = {
    "type": "object",
    "properties": {f: {"type": "string"} for f in FIELDS},
    "required": list(FIELDS),
    "additionalProperties": False,
}


def parse_box(text: str) -> str:
    """Strip the 8 corner coordinates from each OCR line, keep the text."""
    return "\n".join(
        line.split(",", 8)[8] for line in text.splitlines() if line.count(",") >= 8
    )


def cases(data: Path) -> list[Case]:
    """One case per receipt in a SROIE split (`box/`, `img/`, `entities/`), sorted by id."""
    return [
        Case(
            id=box.stem,
            inputs={"text": box, "image": data / "img" / f"{box.stem}.jpg"},
            expected=json.loads((data / "entities" / box.name).read_text()),
            scoring=SCORING,
        )
        for box in sorted((data / "box").glob("*.txt"))
    ]


class SroiePipeline:
    def __init__(self, config: PipelineConfig, client: OpenAI):
        if config.input not in INPUTS:
            raise ValueError(f"input must be one of {INPUTS}, got {config.input!r}")
        self.config = config
        self.client = client
        self.prompt = config.prompt.read_text()

    def content(self, case: Case) -> str | list:
        path = case.inputs[self.config.input]
        if self.config.input == "text":
            return parse_box(path.read_text(encoding="utf-8", errors="replace"))
        jpg = base64.b64encode(path.read_bytes()).decode()
        url = f"data:image/jpeg;base64,{jpg}"
        return [{"type": "image_url", "image_url": {"url": url, "detail": "high"}}]

    def run(self, case: Case) -> Answer:
        start = time.perf_counter()
        try:
            r = self.client.chat.completions.create(
                model=self.config.model,
                **self.config.params,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "receipt",
                        "strict": True,
                        "schema": SCHEMA,
                    },
                },
                messages=[
                    {"role": "system", "content": self.prompt},
                    {"role": "user", "content": self.content(case)},
                ],
            )
        except openai.RateLimitError as e:
            if getattr(e, "code", None) == "insufficient_quota":
                raise Fatal(str(e)) from e
            raise Retryable(str(e)) from e
        except (openai.APIConnectionError, openai.InternalServerError) as e:
            raise Retryable(str(e)) from e
        except (
            openai.AuthenticationError,
            openai.PermissionDeniedError,
            openai.NotFoundError,
        ) as e:
            raise Fatal(str(e)) from e  # wrong key or model: every other call fails too
        latency = time.perf_counter() - start
        raw = r.choices[0].message.content or ""
        try:
            output = json.loads(raw)
        except json.JSONDecodeError:
            output = None
        details = r.usage.completion_tokens_details
        return Answer(
            output=output,
            raw=raw,
            input_tokens=r.usage.prompt_tokens,
            output_tokens=r.usage.completion_tokens,
            latency_s=round(latency, 3),
            model=r.model,
            fingerprint=r.system_fingerprint,
            reasoning_tokens=(details and details.reasoning_tokens) or 0,
            finish_reason=r.choices[0].finish_reason,
            request_id=r.id,
        )


def build(config: PipelineConfig, client: OpenAI | None = None) -> SroiePipeline:
    # The runner retries and counts retries, so the SDK must not retry on its own.
    return SroiePipeline(
        config, client or OpenAI(max_retries=0, timeout=config.timeout_s)
    )


def sleep_then_go_on(seconds: float) -> bool:
    time.sleep(seconds)
    return False


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--config",
        type=Path,
        default=Path("configs/sroie-text.yaml"),
        help="pipeline config; for reasoning models set reasoning_effort, not temperature",
    )
    p.add_argument("-n", type=int, default=10, help="number of receipts")
    p.add_argument(
        "--data", type=Path, default=Path("data/SROIE2019/train"), help="SROIE split"
    )
    p.add_argument(
        "--out",
        type=Path,
        default=Path("data/runs/sroie.jsonl"),
        help="JSONL file to append to",
    )
    args = p.parse_args()
    config = load_config(args.config)
    pipeline = build(config)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    records = []
    print("| case | field | expected | got | ok |\n|---|---|---|---|---|")
    for case in cases(args.data)[: args.n]:
        answer, _, error = call(pipeline, case, config.max_retries, sleep_then_go_on)
        if error:
            raise SystemExit(f"{case.id}: {error}")
        record = {
            "case": case.id,
            "config": str(args.config),
            "input": config.input,
            **config.params,
            **asdict(answer),
            "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
            "hits": score(case.expected, answer.output, case.scoring)["per_field"],
        }
        with args.out.open("a") as f:
            f.write(json.dumps(record) + "\n")
        records.append(record)
        for field, ok in record["hits"].items():
            got = (answer.output or {}).get(field)
            print(
                f"| {case.id} | {field} | {case.expected.get(field)} | {got} | {'✓' if ok else '✗'} |"
            )

    n = len(records)
    print()
    for field in FIELDS:
        verdicts = [r["hits"].get(field) for r in records]
        scored = [v for v in verdicts if v is not None]
        print(f"{field}: {sum(scored)}/{len(scored)}")
    tokens_in = sum(r["input_tokens"] for r in records)
    tokens_out = sum(r["output_tokens"] for r in records)
    latency = sum(r["latency_s"] for r in records) / n
    print(f"tokens in/out: {tokens_in}/{tokens_out}, mean latency: {latency:.2f} s")


if __name__ == "__main__":
    main()
