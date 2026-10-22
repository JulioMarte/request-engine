"""Who can see a called customer: the doctor/room choice behind Today's "Start service".

Starting service is the delivery owner's ``service_session_start`` operation. It
needs a resource that has an active assignment at the queue's location; the
queue entry itself carries no planned resource. The delivery owner publishes
exactly that set as ``front_desk_serving_resources`` (``GET
/v1/locations/{location_id}/serving-resources``), gated by the same
``service_session.start`` capability, so a receptionist who may start service
can see who works here without managing supply.

The console only presents the owner's answer: the owner re-checks the resource,
assignment, revision and capability when service starts. A person without
``service_session.start`` is told so instead of being offered a broken form.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

from request_engine.entrypoints.http.admin_console.json_types import as_list, as_mapping

SERVICE_STAFF_OPERATION_IDS = ("front_desk_serving_resources",)


class OwnerRead(Protocol):
    @property
    def status(self) -> int: ...

    @property
    def payload(self) -> Any: ...

    @property
    def ok(self) -> bool: ...


ReadServingResources = Callable[[str], Awaitable[OwnerRead]]


def _choices() -> dict[str, list[dict[str, str]]]:
    return {}


@dataclass(frozen=True)
class ServiceStaff:
    """Resources that can start service, grouped by location, or why none can be shown.

    ``problem`` is empty when the reads succeeded; otherwise it names what is
    missing: ``capability`` (no ``service_session.start``) or ``unavailable``
    (read failed).
    """

    problem: str = ""
    by_location: dict[str, list[dict[str, str]]] = field(default_factory=_choices)

    def at(self, location_id: str | None) -> list[dict[str, str]]:
        if location_id is not None:
            return self.by_location.get(location_id, [])
        return [choice for choices in self.by_location.values() for choice in choices]


def _choices_from(location_id: str, payload: Any) -> list[dict[str, str]]:
    return [
        {
            "resource_id": str(item.get("resource_id")),
            "location_id": location_id,
            "name": str(item.get("display_name") or "Unnamed"),
        }
        for item in (as_mapping(raw) for raw in as_list(as_mapping(payload).get("items")))
        if item.get("resource_id")
    ]


async def load_service_staff(
    read: ReadServingResources, location_ids: Iterable[str]
) -> ServiceStaff:
    grouped: dict[str, list[dict[str, str]]] = {}
    for location_id in dict.fromkeys(location_ids):
        answer = await read(location_id)
        if not answer.ok:
            return ServiceStaff(problem="capability" if answer.status == 403 else "unavailable")
        grouped[location_id] = _choices_from(location_id, answer.payload)
    return ServiceStaff(by_location=grouped)


__all__ = [
    "SERVICE_STAFF_OPERATION_IDS",
    "ServiceStaff",
    "load_service_staff",
]
