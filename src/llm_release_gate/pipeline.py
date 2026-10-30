"""What the gate knows about a pipeline: cases in, answers out, a YAML config per version. The program that answers
runs in `command.py`."""

import math
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
    model: str | None  # what the provider reports
    fingerprint: str | None = None
    reasoning_tokens: int = 0
    finish_reason: str | None = None
    request_id: str | None = None


class Retryable(Exception):
    """The same run may succeed later: rate limit, timeout, server error."""


class Fatal(Exception):
    """No further run can succeed, e.g. the account is out of quota."""


class Pipeline(Protocol):
    def run(self, case: Case) -> Answer: ...


@dataclass(frozen=True)
class PipelineConfig:
    command: tuple[
        str, ...
    ]  # the program that answers one case: [program, argument, ...]
    model: str
    prompt: (
        Path | dict[str, Path]
    )  # one file, or named files for a pipeline with several prompts
    input: str
    params: dict[str, Any] = field(default_factory=dict)
    max_retries: int = 5
    timeout_s: float = 60.0


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
    optional = {"params", "max_retries", "timeout_s"}
    keys = {"command", "model", "prompt", "input"} | optional
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
    command = raw["command"]
    if not (
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
        command=tuple(command),
        model=raw["model"],
        prompt=prompt,
        input=raw["input"],
        params=plain_numbers(raw.get("params") or {}),
        max_retries=retries,
        timeout_s=float(timeout),  # 60 and 60.0 must hash alike
    )


def is_alias(model: str | None) -> bool:
    """A model name without a date: the provider may change the model behind it (D-018)."""
    return bool(model) and not SNAPSHOT.match(model)


def config_hash(config: PipelineConfig) -> str:
    """Every config field and the bytes of each prompt file; `version.version_hash` adds the project's code."""
    prompt = config.prompt
    return canonical_hash(
        {
            **asdict(config),
            "prompt": file_hash(prompt)
            if isinstance(prompt, Path)
            else {name: file_hash(p) for name, p in prompt.items()},
        }
    )
