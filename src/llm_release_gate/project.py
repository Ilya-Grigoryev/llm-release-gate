"""A project's gate.yaml (`project.schema.json`): its pipelines and how the gate runs them."""

import json
from dataclasses import dataclass, field, replace
from pathlib import Path

import yaml

from llm_release_gate import protocol

FILE = "gate.yaml"
SCHEMA = json.loads((Path(__file__).parent / "project.schema.json").read_text())
VALIDATOR = protocol.Validator(SCHEMA)
SETTINGS = ("k", "delta", "prices", "budgets")


@dataclass(frozen=True)
class Pipeline:
    name: str
    config: str  # paths relative to the project
    golden: str
    manifest: str | None = None
    inputs_url: str | None = None
    k: int = 1
    delta: float = 5.0
    prices: str | None = None
    budgets: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Project:
    prepare: tuple[str, ...] | None
    pipelines: dict[str, Pipeline]
    defaults: dict = field(default_factory=dict)  # the settings at the top

    def rules(self, p: Pipeline) -> Pipeline:
        """`p` under this project's rules (D-024): its own entry's settings, or the top ones for a pipeline it lacks."""
        own = self.pipelines.get(p.name) or Pipeline(
            p.name, p.config, p.golden, **self.defaults
        )
        return replace(p, **{k: getattr(own, k) for k in SETTINGS})


def load(directory: Path) -> Project:
    """Read DIRECTORY/gate.yaml. Raises ValueError naming the file and each broken field."""
    path = Path(directory) / FILE
    try:
        raw = yaml.safe_load(path.read_text())
    except OSError as e:
        raise ValueError(f"{path}: {e.strerror}") from None
    except yaml.YAMLError as e:
        raise ValueError(f"{path}: {e}") from None
    if found := protocol.describe(VALIDATOR, raw):
        raise ValueError(f"{path}: {'; '.join(found)}")
    top = {k: raw[k] for k in SETTINGS if k in raw}
    pipelines = {}
    for name, p in raw["pipelines"].items():
        settings = top | {k: p[k] for k in SETTINGS if k in p}
        if (
            "cost_per_run_usd" in settings.get("budgets", {})
            and "prices" not in settings
        ):
            raise ValueError(
                f"{path}: pipelines.{name}: budgets.cost_per_run_usd needs prices"
            )
        pipelines[name] = Pipeline(
            name,
            p["config"],
            p["golden"],
            p.get("manifest"),
            p.get("inputs-url"),
            **settings,
        )
    return Project(tuple(raw["prepare"]) if "prepare" in raw else None, pipelines, top)
