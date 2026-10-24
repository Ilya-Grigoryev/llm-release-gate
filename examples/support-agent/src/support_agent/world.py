"""The coworking space: tables in memory and the tools that read and change them.

Tools enforce what the booking system would: a space cannot be double-booked, the space is open 08:00-20:00, the past
is closed. Everything else (plans, overlaps per member, credits, escalation) is policy, for the agent to follow.
"""

import copy
from datetime import datetime, timedelta
from pathlib import Path

import yaml

PRICE_EUR = {"desk": 5, "room": 15}
OPEN, CLOSE = 8, 20
TOOLS = (
    "find_member",
    "get_member",
    "list_bookings",
    "search_availability",
    "create_booking",
    "cancel_booking",
    "issue_credit",
    "escalate_to_human",
)


class ToolError(Exception):
    """The tool refused the call. The agent sees the message."""


def tool_specs(path: Path) -> list[dict]:
    """`tools.yaml` as OpenAI function tools."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": {
                    "type": "object",
                    "properties": t["parameters"],
                    "required": t["required"],
                    "additionalProperties": False,
                },
            },
        }
        for t in yaml.safe_load(Path(path).read_text())
    ]


class World:
    def __init__(self, tables: dict, now: str):
        self.tables = copy.deepcopy(tables)
        for name in ("bookings", "credits", "escalations"):
            self.tables.setdefault(name, [])
        self.now = datetime.fromisoformat(now)

    def state(self) -> dict:
        return copy.deepcopy(self.tables)

    def call(self, name: str, args: dict) -> object:
        if name not in TOOLS:
            raise ToolError(f"unknown tool {name}")
        try:
            return getattr(self, name)(**args)
        except TypeError as e:  # missing or unexpected arguments
            raise ToolError(f"bad arguments for {name}: {e}") from None

    # lookups

    def _member(self, member_id: str) -> dict:
        for m in self.tables["members"]:
            if m["id"] == member_id:
                return m
        raise ToolError(f"no member {member_id}")

    def _space(self, space_id: str) -> dict:
        for s in self.tables["spaces"]:
            if s["id"] == space_id:
                return s
        raise ToolError(f"no space {space_id}")

    def _slot(self, start: str, hours: int) -> tuple[datetime, datetime]:
        try:
            begin = datetime.fromisoformat(start)
        except (TypeError, ValueError):
            raise ToolError(f"start must be YYYY-MM-DDTHH:MM, got {start!r}") from None
        if begin.tzinfo:
            raise ToolError("give Vienna local time, without an offset")
        if type(hours) is not int or hours < 1:
            raise ToolError("hours must be a whole number >= 1")
        end = begin + timedelta(hours=hours)
        if begin <= self.now:
            raise ToolError("the slot is in the past")
        if (
            begin.minute
            or begin.hour < OPEN
            or end.date() != begin.date()
            or end.hour > CLOSE
        ):
            raise ToolError(
                f"bookings start on the hour, within {OPEN:02}:00-{CLOSE}:00"
            )
        return begin, end

    def _busy(self, space_id: str, begin: datetime, end: datetime) -> bool:
        for b in self.tables["bookings"]:
            if b["space_id"] == space_id and b["status"] == "active":
                b_begin = datetime.fromisoformat(b["start"])
                if b_begin < end and begin < b_begin + timedelta(hours=b["hours"]):
                    return True
        return False

    def _view(self, b: dict) -> dict:
        kind = self._space(b["space_id"])["kind"]
        return {
            "booking_id": b["id"],
            "space_id": b["space_id"],
            "kind": kind,
            "start": b["start"],
            "hours": b["hours"],
            "price_eur": PRICE_EUR[kind] * b["hours"],
            "status": b["status"],
        }

    # tools

    def find_member(self, email: str) -> dict:
        if not isinstance(email, str):
            raise ToolError("email must be a string")
        for m in self.tables["members"]:
            if m["email"].lower() == email.strip().lower():
                return dict(m)
        raise ToolError(f"no member with email {email}")

    def get_member(self, member_id: str) -> dict:
        return dict(self._member(member_id))

    def list_bookings(self, member_id: str) -> list[dict]:
        self._member(member_id)
        mine = [
            b
            for b in self.tables["bookings"]
            if b["member_id"] == member_id and b["status"] == "active"
        ]
        return [self._view(b) for b in sorted(mine, key=lambda b: b["start"])]

    def search_availability(
        self, kind: str, start: str, hours: int, people: int = 1
    ) -> list[dict]:
        if kind not in PRICE_EUR:
            raise ToolError("kind must be desk or room")
        if type(people) is not int or people < 1:
            raise ToolError("people must be a whole number >= 1")
        begin, end = self._slot(start, hours)
        return [
            {"space_id": s["id"], "name": s["name"], "capacity": s["capacity"]}
            for s in self.tables["spaces"]
            if s["kind"] == kind
            and s["capacity"] >= people
            and not self._busy(s["id"], begin, end)
        ]

    def create_booking(
        self, member_id: str, space_id: str, start: str, hours: int
    ) -> dict:
        self._member(member_id)
        self._space(space_id)
        begin, end = self._slot(start, hours)
        if self._busy(space_id, begin, end):
            raise ToolError(f"{space_id} is taken for part of this slot")
        ids = [int(b["id"].split("-")[1]) for b in self.tables["bookings"]]
        number = max(ids, default=0) + 1
        booking = {
            "id": f"B-{number}",
            "member_id": member_id,
            "space_id": space_id,
            "start": begin.isoformat(timespec="minutes"),
            "hours": hours,
            "status": "active",
        }
        self.tables["bookings"].append(booking)
        return self._view(booking)

    def cancel_booking(self, booking_id: str) -> dict:
        for b in self.tables["bookings"]:
            if b["id"] == booking_id:
                if b["status"] != "active":
                    raise ToolError(f"{booking_id} is already cancelled")
                if datetime.fromisoformat(b["start"]) <= self.now:
                    raise ToolError(f"{booking_id} has already started")
                b["status"] = "cancelled"
                return self._view(b)
        raise ToolError(f"no booking {booking_id}")

    def issue_credit(self, member_id: str, amount_eur: float, reason: str) -> dict:
        self._member(member_id)
        if type(amount_eur) not in (int, float) or amount_eur <= 0:
            raise ToolError("amount_eur must be a positive number")
        amount_eur = round(float(amount_eur), 2)  # 15 and 15.0 must store alike
        credits = self.tables["credits"]
        credits.append(
            {"member_id": member_id, "amount_eur": amount_eur, "reason": reason}
        )
        return {"credit_id": f"C-{len(credits)}", "amount_eur": amount_eur}

    def escalate_to_human(self, member_id: str, summary: str) -> dict:
        self._member(member_id)
        escalations = self.tables["escalations"]
        escalations.append({"member_id": member_id, "summary": summary})
        return {"ticket": f"T-{len(escalations)}", "status": "staff will follow up"}


def diff(before: dict, after: dict) -> dict:
    """What changed, in the terms a case declares. Desks are interchangeable, so a new desk booking is `desk`."""
    kinds = {s["id"]: s["kind"] for s in after["spaces"]}
    old = {b["id"]: b for b in before["bookings"]}
    changes = {
        "created": [
            {
                "member_id": b["member_id"],
                "space": "desk" if kinds[b["space_id"]] == "desk" else b["space_id"],
                "start": b["start"],
                "hours": b["hours"],
            }
            for b in after["bookings"]
            if b["id"] not in old and b["status"] == "active"
        ],
        "cancelled": sorted(
            b["id"]
            for b in after["bookings"]
            if b["id"] in old
            and old[b["id"]]["status"] == "active"
            and b["status"] == "cancelled"
        ),
        "credits": [
            {"member_id": c["member_id"], "amount_eur": c["amount_eur"]}
            for c in after["credits"][len(before["credits"]) :]
        ],
        "escalations": [
            e["member_id"] for e in after["escalations"][len(before["escalations"]) :]
        ],
    }
    return {k: v for k, v in changes.items() if v}
