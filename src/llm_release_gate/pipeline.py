"""What the gate knows about a pipeline: cases in, answers out, a YAML config per version."""

import importlib
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

import yaml

from llm_release_gate.hashing import canonical_hash, file_hash

SNAPSHOT = re.compile(r".+-(\d{4}-\d{2}-\d{2}|\d{8})$")


@dataclass(frozen=True)
class Case:
    id: str
    inputs: dict[str, Path]
    expected: dict[str, Any]
    scoring: dict[str, Any] = field(default_factory=dict)


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


class Retryable(Exception):
    """Raised by a pipeline when the same call may succeed later: rate limit, timeout, server error."""


class Fatal(Exception):
    """Raised by a pipeline when no further call can succeed, e.g. the account is out of quota."""


class Pipeline(Protocol):
    def run(self, case: Case) -> Answer: ...


@dataclass(frozen=True)
class PipelineConfig:
    pipeline: str
    model: str
    prompt: Path
    input: str
    params: dict[str, Any] = field(default_factory=dict)
    max_retries: int = 5
    timeout_s: float = 60.0


def load_config(path: Path) -> PipelineConfig:
    """Read a pipeline config. The prompt path is relative to the config file."""
    raw = yaml.safe_load(Path(path).read_text())
    optional = {"params", "max_retries", "timeout_s"}
    keys = {"pipeline", "model", "prompt", "input"} | optional
    if not isinstance(raw, dict) or not raw.keys() <= keys:
        raise ValueError(f"{path}: expected a mapping with keys from {sorted(keys)}")
    missing = keys - optional - raw.keys()
    if missing:
        raise ValueError(f"{path}: missing {sorted(missing)}")
    retries, timeout = raw.get("max_retries", 5), raw.get("timeout_s", 60)
    if type(retries) is not int or retries < 0:
        raise ValueError(f"{path}: max_retries must be an integer >= 0")
    if type(timeout) not in (int, float) or timeout <= 0:
        raise ValueError(f"{path}: timeout_s must be a number > 0")
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
        max_retries=retries,
        timeout_s=float(timeout),  # 60 and 60.0 must hash alike
    )


def config_hash(config: PipelineConfig) -> str:
    """Identity of a pipeline version: every config field plus the bytes of the prompt file."""
    return canonical_hash({**asdict(config), "prompt": file_hash(config.prompt)})


def load_pipeline(config: PipelineConfig, **kwargs) -> Pipeline:
    """Build the pipeline named in the config from `llm_release_gate.pipelines.<name>`."""
    module = importlib.import_module(f"llm_release_gate.pipelines.{config.pipeline}")
    return module.build(config, **kwargs)
