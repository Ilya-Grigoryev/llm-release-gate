"""SROIE pipeline: receipt OCR text or scan -> LLM -> company, date, address, total."""

import argparse
import base64
import json
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from openai import OpenAI

from llm_release_gate.pipeline import Answer, Case, PipelineConfig, load_config

FIELDS = ("company", "date", "address", "total")
INPUTS = ("text", "image")
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


def normalize(value: str | None) -> str:
    return " ".join((value or "").split()).casefold()


def field_hits(expected: dict, got: dict) -> dict[str, bool]:
    return {f: normalize(expected.get(f)) == normalize(got.get(f)) for f in FIELDS}


def cases(data: Path) -> list[Case]:
    """One case per receipt in a SROIE split (`box/`, `img/`, `entities/`), sorted by id."""
    return [
        Case(
            id=box.stem,
            inputs={"text": box, "image": data / "img" / f"{box.stem}.jpg"},
            expected=json.loads((data / "entities" / box.name).read_text()),
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
        r = self.client.chat.completions.create(
            model=self.config.model,
            **self.config.params,
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "receipt", "strict": True, "schema": SCHEMA},
            },
            messages=[
                {"role": "system", "content": self.prompt},
                {"role": "user", "content": self.content(case)},
            ],
        )
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
        )


def build(config: PipelineConfig, client: OpenAI | None = None) -> SroiePipeline:
    return SroiePipeline(config, client or OpenAI())


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, default=Path("configs/sroie-text.yaml"))
    p.add_argument("-n", type=int, default=10, help="number of receipts")
    p.add_argument("--data", type=Path, default=Path("data/SROIE2019/train"))
    p.add_argument("--out", type=Path, default=Path("data/runs/sroie.jsonl"))
    args = p.parse_args()
    config = load_config(args.config)
    pipeline = build(config)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    records = []
    print("| case | field | expected | got | ok |\n|---|---|---|---|---|")
    for case in cases(args.data)[: args.n]:
        answer = pipeline.run(case)
        record = {
            "case": case.id,
            "config": str(args.config),
            "input": config.input,
            **config.params,
            **asdict(answer),
            "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
            "hits": field_hits(case.expected, answer.output or {}),
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
        print(f"{field}: {sum(r['hits'][field] for r in records)}/{n}")
    tokens_in = sum(r["input_tokens"] for r in records)
    tokens_out = sum(r["output_tokens"] for r in records)
    latency = sum(r["latency_s"] for r in records) / n
    print(f"tokens in/out: {tokens_in}/{tokens_out}, mean latency: {latency:.2f} s")


if __name__ == "__main__":
    main()
