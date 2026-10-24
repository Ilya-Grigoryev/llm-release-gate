"""SROIE pipeline: receipt OCR text or scan -> LLM -> company, date, address, total."""

import base64
import json
import time
from pathlib import Path

import openai
from openai import OpenAI

from llm_release_gate.pipeline import (
    Answer,
    Case,
    Fatal,
    PipelineConfig,
    Retryable,
)

VERSION = 1  # bump when the request changes: schema, message layout, image detail
FIELDS = ("company", "date", "address", "total")
INPUTS = ("text", "image")
# D-005: text fields compared after whitespace and case folding, date and total by value.
SCORING = {
    "method": "field_match",
    "normalise": ["whitespace", "casefold"],
    "fields": {"date": {"type": "date"}, "total": {"type": "number"}},
}
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


def labels(path: Path, empty_as_null: bool = True) -> dict:
    """Expected values of one receipt. An empty label means unlabelled (null), so it is not scored (D-005)."""
    raw = json.loads(path.read_text())
    return (
        {k: (None if v == "" else v) for k, v in raw.items()} if empty_as_null else raw
    )


def cases(data: Path, empty_as_null: bool = True) -> list[Case]:
    """One case per receipt in a SROIE split (`box/`, `img/`, `entities/`), sorted by id."""
    return [
        Case(
            id=box.stem,
            inputs={"text": box, "image": data / "img" / f"{box.stem}.jpg"},
            expected=labels(data / "entities" / box.name, empty_as_null),
            scoring=SCORING,
        )
        for box in sorted((data / "box").glob("*.txt"))
    ]


class SroiePipeline:
    def __init__(self, config: PipelineConfig, client: OpenAI):
        if config.input not in INPUTS:
            raise ValueError(f"input must be one of {INPUTS}, got {config.input!r}")
        if not isinstance(config.prompt, Path):
            raise ValueError("prompt must be one file")  # noqa: TRY004 - a config error
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
        return self.ask(self.prompt, self.content(case))

    def ask(self, system: str, content: str | list) -> Answer:
        """One call that answers with the four fields."""
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
                    {"role": "system", "content": system},
                    {"role": "user", "content": content},
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
