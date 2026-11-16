"""A project's gate.yaml (`project.schema.json`): its pipelines and how the gate runs them."""

import json
from dataclasses import dataclass, field, replace
from pathlib import Path

import yaml

from llm_release_gate import protocol

FILE = "gate.yaml"
SCHEMA = json.loads((Path(__file__).parent / "project.schema.json").read_text())
VALIDATOR = protocol.Validator(SCHEMA)
SETTINGS = (
    "k",
    "delta",
    "alpha",
    "mean",
    "checks",
    "levels",
    "prices",
    "budgets",
    "base_max_age_days",
    "max_spend_usd",
)


@dataclass(frozen=True)
class Pipeline:
    name: str
    config: str  # paths relative to the project
    golden: str
    manifest: str | None = None
    inputs_url: str | None = None
    k: int = 1
    delta: float = 5.0
    alpha: float = 0.05  # the whole gate's, split between the rules (D-031)
    mean: str = "naive"  # rule on the mean: naive or betting (D-026)
    checks: str = "block"  # the rule on checks blocks or only reports (D-003)
    levels: dict = field(
        default_factory=dict
    )  # critical / minor checks and cases (D-028)
    prices: str | None = None
    budgets: dict = field(default_factory=dict)
    base_max_age_days: float = 7.0
    max_spend_usd: float | None = None  # adaptive runs instead of `k` (D-032)

    @property
    def checks_block(self) -> bool:
        """Whether a check may block, by the settings alone: `checks: block`, or a critical level."""
        levels = self.levels or {}
        return (
            self.checks == "block"
            or bool(levels.get("critical"))
            or "critical" in levels.get("cases", {}).values()
        )


@dataclass(frozen=True)
class Project:
    prepare: tuple[str, ...] | None
    pipelines: dict[str, Pipeline]
    defaults: dict = field(default_factory=dict)  # the settings at the top
    ignore: tuple[str, ...] = ()

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
    for where, given in (
        ("", raw),
        *((f"pipelines.{n}.", p) for n, p in raw["pipelines"].items()),
    ):
        for k in ("delta", "alpha"):
            if k in given and given[k] != given[k]:  # NaN passes the schema's bounds
                raise ValueError(f"{path}: {where}{k} is not a number")
    top = {k: raw[k] for k in SETTINGS if k in raw}
    if "cost_per_run_usd" in top.get("budgets", {}) and "prices" not in top:
        raise ValueError(f"{path}: budgets.cost_per_run_usd needs prices")
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
        if "max_spend_usd" in settings:
            for need, ok in (
                ("prices", "prices" in settings),
                ("mean: betting", settings.get("mean") == "betting"),
            ):
                if not ok:
                    raise ValueError(
                        f"{path}: pipelines.{name}: max_spend_usd needs {need}"
                    )
        pipelines[name] = Pipeline(
            name,
            p["config"],
            p["golden"],
            p.get("manifest"),
            p.get("inputs-url"),
            **settings,
        )
    return Project(
        tuple(raw["prepare"]) if "prepare" in raw else None,
        pipelines,
        top,
        tuple(raw.get("ignore", ())),
    )
