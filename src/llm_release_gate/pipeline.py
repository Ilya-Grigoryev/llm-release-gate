"""What the gate knows about a pipeline: cases in, answers out, a YAML config per version."""

import importlib
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import ModuleType
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
    model: str | None  # what the provider reports
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
    prompt: (
        Path | dict[str, Path]
    )  # one file, or named files for a pipeline with several prompts
    input: str
    params: dict[str, Any] = field(default_factory=dict)
    max_retries: int = 5
    timeout_s: float = 60.0
    command: tuple[str, ...] | None = None  # `pipeline: command` runs this program


def plain_numbers(value: Any) -> Any:
    """Turn whole floats into ints, nested too, so `temperature: 0` and `0.0` hash alike."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {k: plain_numbers(v) for k, v in value.items()}
    if isinstance(value, list):
        return [plain_numbers(v) for v in value]
    return value


def prompt_files(raw: Any, base: Path) -> Path | dict[str, Path]:
    """`prompt:` is one file or a mapping of names to files, relative to `base`."""
    if isinstance(raw, str):
        return base / raw
    if (
        isinstance(raw, dict)
        and raw
        and all(isinstance(k, str) and isinstance(v, str) for k, v in raw.items())
    ):
        return {name: base / ref for name, ref in raw.items()}
    raise ValueError(
        f"prompt must be a file or a mapping of names to files, got {raw!r}"
    )


def load_config(path: Path) -> PipelineConfig:
    """Read a pipeline config. Prompt paths are relative to the config file."""
    raw = yaml.safe_load(Path(path).read_text())
    optional = {"params", "max_retries", "timeout_s", "command"}
    keys = {"pipeline", "model", "prompt", "input"} | optional
    if not isinstance(raw, dict) or not raw.keys() <= keys:
        raise ValueError(f"{path}: expected a mapping with keys from {sorted(keys)}")
    missing = keys - optional - raw.keys()
    if missing:
        raise ValueError(f"{path}: missing {sorted(missing)}")
    retries, timeout = raw.get("max_retries", 5), raw.get("timeout_s", 60)
    if type(retries) is not int or retries < 0:
        raise ValueError(f"{path}: max_retries must be an integer >= 0")
    if type(timeout) not in (int, float) or not 0 < timeout < math.inf:
        raise ValueError(f"{path}: timeout_s must be a finite number > 0")
    if not isinstance(raw["input"], str):
        raise ValueError(f"{path}: input must be a name, got {raw['input']!r}")  # noqa: TRY004 - a config error like the others
    if not isinstance(raw["model"], str) or not raw["model"]:
        raise ValueError(f"{path}: model must be a name, got {raw['model']!r}")
    command = raw.get("command")
    if (raw["pipeline"] == "command") != (command is not None):
        raise ValueError(
            f"{path}: `command` goes with `pipeline: command`, and only with it"
        )
    if command is not None and not (
        isinstance(command, list)
        and command
        and all(isinstance(c, str) and c for c in command)
    ):
        raise ValueError(f"{path}: command must be a list: [program, argument, ...]")
    try:
        prompt = prompt_files(raw["prompt"], Path(path).parent)
    except ValueError as e:
        raise ValueError(f"{path}: {e}") from None
    return PipelineConfig(
        pipeline=raw["pipeline"],
        model=raw["model"],
        prompt=prompt,
        input=raw["input"],
        params=plain_numbers(raw.get("params") or {}),
        max_retries=retries,
        timeout_s=float(timeout),  # 60 and 60.0 must hash alike
        command=tuple(command) if command else None,
    )


def is_alias(model: str | None) -> bool:
    """A model name without a date: the provider may change the model behind it (D-018)."""
    return bool(model) and not SNAPSHOT.match(model)


def pipeline_module(name: str) -> ModuleType:
    """The module named in `pipeline:` by its import path, e.g. `my_app.gate_adapter`; `command` is the gate's own."""
    if name == "command":
        name = "llm_release_gate.command"
    try:
        module = importlib.import_module(name)
    except Exception as e:  # foreign code: any failure here is a config error
        raise ValueError(
            f"pipeline {name!r}: cannot import ({type(e).__name__}: {e})"
        ) from e
    if not callable(getattr(module, "build", None)):
        raise ValueError(f"pipeline {name!r}: no build(config) function")  # noqa: TRY004 - a config error like the others
    return module


def config_hash(config: PipelineConfig) -> str:
    """Identity of a pipeline version: every config field, the bytes of each prompt file and the
    pipeline module's VERSION, which the module bumps when its code changes what the model is asked."""
    module = pipeline_module(config.pipeline)
    prompt = config.prompt
    fields = asdict(config)
    if fields["command"] is None:  # configs from before `command` keep their hash
        del fields["command"]
    return canonical_hash(
        {
            **fields,
            "prompt": file_hash(prompt)
            if isinstance(prompt, Path)
            else {name: file_hash(p) for name, p in prompt.items()},
            "pipeline_version": getattr(module, "VERSION", None),
        }
    )


def load_pipeline(config: PipelineConfig, **kwargs) -> Pipeline:
    """Build the pipeline with the `build(config)` function of the module named in the config."""
    return pipeline_module(config.pipeline).build(config, **kwargs)
