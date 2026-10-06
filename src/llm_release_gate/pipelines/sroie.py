"""SROIE pipeline: OCR text of a receipt -> LLM -> company, date, address, total."""

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from openai import OpenAI

FIELDS = ("company", "date", "address", "total")
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


def extract(client: OpenAI, prompt: str, ocr: str, model: str, seed: int) -> dict:
    start = time.perf_counter()
    r = client.chat.completions.create(
        model=model,
        temperature=0,
        seed=seed,
        max_completion_tokens=300,
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "receipt", "strict": True, "schema": SCHEMA},
        },
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": ocr},
        ],
    )
    return {
        "output": json.loads(r.choices[0].message.content),
        "model": r.model,
        "fingerprint": r.system_fingerprint,
        "seed": seed,
        "input_tokens": r.usage.prompt_tokens,
        "output_tokens": r.usage.completion_tokens,
        "latency_s": round(time.perf_counter() - start, 3),
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("-n", type=int, default=10, help="number of receipts")
    p.add_argument("--data", type=Path, default=Path("data/SROIE2019/train"))
    p.add_argument("--prompt", type=Path, default=Path("prompts/sroie.md"))
    p.add_argument("--model", default="gpt-4.1-mini-2025-04-14")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", type=Path, default=Path("data/runs/sroie.jsonl"))
    args = p.parse_args()

    prompt = args.prompt.read_text()
    client = OpenAI()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    records = []
    print("| case | field | expected | got | ok |\n|---|---|---|---|---|")
    for path in sorted((args.data / "box").glob("*.txt"))[: args.n]:
        ocr = parse_box(path.read_text(encoding="utf-8", errors="replace"))
        expected = json.loads((args.data / "entities" / path.name).read_text())
        record = {
            "case": path.stem,
            **extract(client, prompt, ocr, args.model, args.seed),
        }
        record["hits"] = field_hits(expected, record["output"])
        with args.out.open("a") as f:
            f.write(json.dumps(record) + "\n")
        records.append(record)
        for field, ok in record["hits"].items():
            got = record["output"][field]
            print(
                f"| {path.stem} | {field} | {expected.get(field)} | {got} | {'✓' if ok else '✗'} |"
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
