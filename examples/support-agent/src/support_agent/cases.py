"""Test cases: a ticket and a user scenario, the starting world, and what a correct agent does."""

from dataclasses import dataclass
from pathlib import Path

import yaml

from support_agent.world import World, diff

CATEGORIES = ("happy", "policy", "refusal", "escalation", "ambiguous")


@dataclass(frozen=True)
class SupportCase:
    id: str
    category: str
    now: str
    ticket: str  # the request in one message, for the no-user mode
    user: dict  # `known` and `instructions` for the user simulator
    tables: dict  # the starting world: cases/world.yaml plus the case's own rows
    actions: list  # [tool, args] pairs a correct agent calls, in order
    expect: dict  # the change those actions make, as `diff` reports it

    def world(self) -> World:
        return World(self.tables, self.now)


def load_case(path: Path) -> SupportCase:
    path = Path(path)
    raw = yaml.safe_load(path.read_text())
    tables = yaml.safe_load((path.parent / "world.yaml").read_text())
    for name, rows in (raw.get("world") or {}).items():
        tables.setdefault(name, []).extend(rows)
    if raw["category"] not in CATEGORIES:
        raise ValueError(f"{path}: category must be one of {CATEGORIES}")
    return SupportCase(
        id=raw["id"],
        category=raw["category"],
        now=str(raw["now"]),
        ticket=raw["ticket"].strip(),
        user=raw["user"],
        tables=tables,
        actions=[(tool, args) for tool, args in raw["actions"]],
        expect=raw.get("expect") or {},
    )


def load_cases(folder: Path) -> list[SupportCase]:
    return [
        load_case(p)
        for p in sorted(Path(folder).glob("*.yaml"))
        if p.name != "world.yaml"
    ]


def reference(case: SupportCase) -> tuple[World, dict]:
    """Run the case's actions on a fresh world: the end state a correct agent reaches, and its diff."""
    world = case.world()
    before = world.state()
    for tool, args in case.actions:
        world.call(tool, args)
    return world, diff(before, world.state())
