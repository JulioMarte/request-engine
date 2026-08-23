from datetime import datetime
from decimal import Decimal
from typing import Literal, cast
from uuid import UUID

import httpx

from request_engine.modules.booking.contracts.appointments import AppointmentSlot, ResourceChoice
from request_engine.modules.booking.contracts.discovery import PublishedSlotQuery

_ENDPOINT = "/internal/v1/discovery/published-slots"


class HttpPublishedSlotReader:
    """Remote Booking availability client for the public Discovery process."""

    trust_boundary: Literal["remote"] = "remote"

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def find_published_slots(
        self,
        query: PublishedSlotQuery,
    ) -> tuple[AppointmentSlot, ...]:
        response = await self._client.post(_ENDPOINT, json=_query_payload(query))
        response.raise_for_status()
        payload = cast(object, response.json())
        if not isinstance(payload, list):
            raise RuntimeError("discovery availability gateway returned a malformed payload")
        items = cast(list[object], payload)
        return tuple(_slot(item) for item in items)


def _query_payload(query: PublishedSlotQuery) -> dict[str, object]:
    return {
        "organization_id": str(query.organization_id),
        "publication_id": str(query.publication_id),
        "publication_revision": query.publication_revision,
        "mapping_id": str(query.mapping_id),
        "mapping_revision": query.mapping_revision,
        "offering_version_id": str(query.offering_version_id),
        "window_start": query.window_start.isoformat(),
        "window_end": query.window_end.isoformat(),
        "location_id": str(query.location_id),
        "resource_id": str(query.resource_id) if query.resource_id is not None else None,
        "limit": query.limit,
    }


def _slot(raw: object) -> AppointmentSlot:
    if not isinstance(raw, dict):
        raise RuntimeError("discovery availability slot is malformed")
    data = cast(dict[str, object], raw)
    resources_raw = data.get("resources")
    if not isinstance(resources_raw, list) or not resources_raw:
        raise RuntimeError("discovery availability resources are malformed")
    resources = cast(list[object], resources_raw)
    return AppointmentSlot(
        offering_version_id=UUID(str(data["offering_version_id"])),
        start_at=datetime.fromisoformat(str(data["start_at"])),
        end_at=datetime.fromisoformat(str(data["end_at"])),
        location_id=_uuid_or_none(data.get("location_id")),
        resources=tuple(_resource(item) for item in resources),
        planned_duration_minutes=_int_or_none(data.get("planned_duration_minutes")),
        amount=_decimal_or_none(data.get("amount")),
        currency=_str_or_none(data.get("currency")),
        location_operational_revision=_int_or_none(data.get("location_operational_revision")),
        configuration_fingerprint=_str_or_none(data.get("configuration_fingerprint")),
    )


def _resource(raw: object) -> ResourceChoice:
    if not isinstance(raw, dict):
        raise RuntimeError("discovery availability resource is malformed")
    data = cast(dict[str, object], raw)
    return ResourceChoice(
        requirement_id=UUID(str(data["requirement_id"])),
        resource_id=UUID(str(data["resource_id"])),
        resource_location_assignment_id=_uuid_or_none(data.get("resource_location_assignment_id")),
        assignment_revision=_int_or_none(data.get("assignment_revision")),
        availability_revision=_int_or_none(data.get("availability_revision")),
    )


def _uuid_or_none(value: object) -> UUID | None:
    return None if value is None else UUID(str(value))


def _int_or_none(value: object) -> int | None:
    return None if value is None else int(str(value))


def _decimal_or_none(value: object) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _str_or_none(value: object) -> str | None:
    return None if value is None else str(value)
