"""What the gate knows about a pipeline: cases in, answers out, a YAML config per version."""

import importlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import yaml

SNAPSHOT = re.compile(r".+-(\d{4}-\d{2}-\d{2}|\d{8})$")


@dataclass(frozen=True)
class Case:
    id: str
    inputs: dict[str, Path]
    expected: dict[str, Any]


@dataclass(frozen=True)
class Answer:
    output: dict[str, Any] | None  # None if `raw` is not valid JSON
    raw: str
    input_tokens: int
    output_tokens: int
    latency_s: float
    model: str  # what the provider reports
    fingerprint: str | None = None
    reasoning_tokens: int = 0
    finish_reason: str | None = None
    request_id: str | None = None


class Pipeline(Protocol):
    def run(self, case: Case) -> Answer: ...


@dataclass(frozen=True)
class PipelineConfig:
    pipeline: str
    model: str
    prompt: Path
    input: str
    params: dict[str, Any] = field(default_factory=dict)


def load_config(path: Path) -> PipelineConfig:
    """Read a pipeline config. The prompt path is relative to the config file."""
    raw = yaml.safe_load(Path(path).read_text())
    keys = {"pipeline", "model", "prompt", "input", "params"}
    if not isinstance(raw, dict) or not raw.keys() <= keys:
        raise ValueError(f"{path}: expected a mapping with keys from {sorted(keys)}")
    missing = keys - {"params"} - raw.keys()
    if missing:
        raise ValueError(f"{path}: missing {sorted(missing)}")
    if not SNAPSHOT.match(raw["model"]):
        raise ValueError(
            f"{path}: model must be a dated snapshot, got {raw['model']!r}"
        )
    return PipelineConfig(
        pipeline=raw["pipeline"],
        model=raw["model"],
        prompt=Path(path).parent / raw["prompt"],
        input=raw["input"],
        params=raw.get("params") or {},
    )


def load_pipeline(config: PipelineConfig, **kwargs) -> Pipeline:
    """Build the pipeline named in the config from `llm_release_gate.pipelines.<name>`."""
    module = importlib.import_module(f"llm_release_gate.pipelines.{config.pipeline}")
    return module.build(config, **kwargs)
