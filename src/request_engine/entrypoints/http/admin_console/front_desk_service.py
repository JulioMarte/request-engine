"""Who can see a called customer: the doctor/room choice behind Today's "Start service".

Starting service is the delivery owner's ``service_session_start`` operation. It
needs a resource that has an active assignment at the queue's location; the
queue entry itself carries no planned resource, and the day board carries none
for booked customers either. The only truthful source of "who works where" is
the booking supply reads (``booking_resource_list`` and
``booking_resource_assignment_list``), which the owner scopes to the Party the
signed-in person represents with ``operations.manage_supply``. That Party comes
from the owner's own self-authority snapshot (``authority_read_self``).

Filtering by location and current assignment window is presentation only: the
owner re-checks the assignment, revision and capability when service starts. A
person whose permissions do not include these reads is told exactly which one is
missing instead of being offered a broken form.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from request_engine.entrypoints.http.admin_console.json_types import as_list, as_mapping

SUPPLY_SCOPE = "operations.manage_supply"
SERVICE_STAFF_OPERATION_IDS = (
    "authority_read_self",
    "booking_resource_list",
    "booking_resource_assignment_list",
)
_PAGE_LIMIT = "100"
_MAX_PAGES = 10


class OwnerRead(Protocol):
    @property
    def status(self) -> int: ...

    @property
    def payload(self) -> Any: ...

    @property
    def ok(self) -> bool: ...


ReadPage = Callable[[str, dict[str, str]], Awaitable[OwnerRead]]


def _choices() -> dict[str, list[dict[str, str]]]:
    return {}


@dataclass(frozen=True)
class ServiceStaff:
    """Resources that can start service, grouped by location, or why none can be shown.

    ``problem`` is empty when the reads succeeded; otherwise it names what is
    missing: ``capability`` (no supply read permission), ``authority`` (no
    business Party represented for supply) or ``unavailable`` (read failed).
    """

    problem: str = ""
    by_location: dict[str, list[dict[str, str]]] = field(default_factory=_choices)

    def at(self, location_id: str | None) -> list[dict[str, str]]:
        if location_id is not None:
            return self.by_location.get(location_id, [])
        return [choice for choices in self.by_location.values() for choice in choices]


def _problem(status: int) -> str:
    return "capability" if status == 403 else "unavailable"


async def _supply_party(read: ReadPage) -> tuple[str | None, int]:
    params = {"limit": _PAGE_LIMIT}
    for _ in range(_MAX_PAGES):
        answer = await read("authority_read_self", params)
        if not answer.ok:
            return None, answer.status
        snapshot = as_mapping(answer.payload)
        for raw in as_list(snapshot.get("representations")):
            item = as_mapping(raw)
            party = item.get("represented_party_id")
            if item.get("scope_key") == SUPPLY_SCOPE and isinstance(party, str) and party:
                return party, 200
        following = snapshot.get("next_after")
        if not following:
            break
        params = {"limit": _PAGE_LIMIT, "after": str(following)}
    return None, 200


async def _collect(
    read: ReadPage, operation_id: str, party: str
) -> tuple[list[dict[str, Any]], int]:
    items: list[dict[str, Any]] = []
    params = {"authority_party_id": party, "limit": _PAGE_LIMIT}
    for _ in range(_MAX_PAGES):
        answer = await read(operation_id, params)
        if not answer.ok:
            return items, answer.status
        page = as_mapping(answer.payload)
        items.extend(dict(as_mapping(item)) for item in as_list(page.get("items")))
        following = page.get("next_cursor")
        if not following:
            break
        params = {**params, "after": str(following)}
    return items, 200


def _instant(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _assigned_now(assignment: dict[str, Any], now: datetime) -> bool:
    start = _instant(assignment.get("effective_from"))
    end = _instant(assignment.get("effective_until"))
    return (
        assignment.get("status") == "active"
        and start is not None
        and start <= now
        and (end is None or now < end)
    )


def group_by_location(
    resources: list[dict[str, Any]], assignments: list[dict[str, Any]], now: datetime
) -> dict[str, list[dict[str, str]]]:
    """Active resources with an assignment in force now, per location, sorted by name."""

    names = {
        str(item.get("resource_id")): str(item.get("display_name") or "Unnamed")
        for item in resources
        if item.get("active") is True
    }
    grouped: dict[str, dict[str, str]] = {}
    for assignment in assignments:
        resource_id = str(assignment.get("resource_id"))
        location_id = assignment.get("location_id")
        if resource_id not in names or not isinstance(location_id, str):
            continue
        if _assigned_now(assignment, now):
            grouped.setdefault(location_id, {})[resource_id] = names[resource_id]
    return {
        location_id: [
            {"resource_id": resource_id, "location_id": location_id, "name": name}
            for resource_id, name in sorted(people.items(), key=lambda item: item[1].casefold())
        ]
        for location_id, people in grouped.items()
    }


async def load_service_staff(read: ReadPage, now: datetime) -> ServiceStaff:
    party, status = await _supply_party(read)
    if status != 200:
        return ServiceStaff(problem=_problem(status))
    if party is None:
        return ServiceStaff(problem="authority")
    (resources, resource_status), (assignments, assignment_status) = (
        await _collect(read, "booking_resource_list", party),
        await _collect(read, "booking_resource_assignment_list", party),
    )
    for answer in (resource_status, assignment_status):
        if answer != 200:
            return ServiceStaff(problem=_problem(answer))
    return ServiceStaff(by_location=group_by_location(resources, assignments, now))


__all__ = [
    "SERVICE_STAFF_OPERATION_IDS",
    "SUPPLY_SCOPE",
    "ServiceStaff",
    "group_by_location",
    "load_service_staff",
]
