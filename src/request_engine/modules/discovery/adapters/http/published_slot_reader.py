from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Literal, cast
from uuid import UUID

import httpx

from request_engine.modules.booking.contracts.appointments import AppointmentSlot, ResourceChoice
from request_engine.modules.booking.contracts.discovery import PublishedSlotQuery

_ENDPOINT = "/internal/v1/discovery/published-slots"
_BATCH_ENDPOINT = "/internal/v1/discovery/published-slots/batch"


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
        return _slots(cast(object, response.json()))

    async def find_published_slots_batch(
        self,
        queries: tuple[PublishedSlotQuery, ...],
    ) -> tuple[tuple[AppointmentSlot, ...], ...]:
        if not queries:
            return ()
        response = await self._client.post(
            _BATCH_ENDPOINT,
            json={"queries": [_query_payload(query) for query in queries]},
        )
        response.raise_for_status()
        payload = cast(object, response.json())
        if not isinstance(payload, list):
            raise RuntimeError("discovery availability batch returned a malformed payload")
        items = cast(list[object], payload)
        if len(items) != len(queries):
            raise RuntimeError("discovery availability batch returned a malformed payload")
        return tuple(_slots(item) for item in items)


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


def _slots(raw: object) -> tuple[AppointmentSlot, ...]:
    if not isinstance(raw, list):
        raise RuntimeError("discovery availability gateway returned a malformed payload")
    return tuple(_slot(item) for item in cast(list[object], raw))


def _slot(raw: object) -> AppointmentSlot:
    if not isinstance(raw, dict):
        raise RuntimeError("discovery availability slot is malformed")
    data = cast(dict[str, object], raw)
    resources_raw = data.get("resources")
    if not isinstance(resources_raw, list) or not resources_raw:
        raise RuntimeError("discovery availability resources are malformed")
    resources = cast(list[object], resources_raw)
    return AppointmentSlot(
        offering_version_id=_uuid(data, "offering_version_id"),
        start_at=_datetime(data, "start_at"),
        end_at=_datetime(data, "end_at"),
        location_id=_uuid(data, "location_id"),
        resources=tuple(_resource(item) for item in resources),
        planned_duration_minutes=_positive_int(data, "planned_duration_minutes"),
        amount=_non_negative_decimal(data, "amount"),
        currency=_required_str(data, "currency"),
        location_operational_revision=_positive_int(data, "location_operational_revision"),
        configuration_fingerprint=_required_str(data, "configuration_fingerprint"),
    )


def _resource(raw: object) -> ResourceChoice:
    if not isinstance(raw, dict):
        raise RuntimeError("discovery availability resource is malformed")
    data = cast(dict[str, object], raw)
    return ResourceChoice(
        requirement_id=_uuid(data, "requirement_id"),
        resource_id=_uuid(data, "resource_id"),
        resource_location_assignment_id=_uuid(data, "resource_location_assignment_id"),
        assignment_revision=_positive_int(data, "assignment_revision"),
        availability_revision=_positive_int(data, "availability_revision"),
    )


def _uuid(data: dict[str, object], key: str) -> UUID:
    value = data.get(key)
    if not isinstance(value, str):
        raise RuntimeError(f"discovery availability {key} is malformed")
    try:
        return UUID(value)
    except ValueError as exc:
        raise RuntimeError(f"discovery availability {key} is malformed") from exc


def _datetime(data: dict[str, object], key: str) -> datetime:
    value = data.get(key)
    if not isinstance(value, str):
        raise RuntimeError(f"discovery availability {key} is malformed")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise RuntimeError(f"discovery availability {key} is malformed") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RuntimeError(f"discovery availability {key} must be timezone-aware")
    return parsed


def _positive_int(data: dict[str, object], key: str) -> int:
    value = data.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise RuntimeError(f"discovery availability {key} is malformed")
    return value


def _non_negative_decimal(data: dict[str, object], key: str) -> Decimal:
    value = data.get(key)
    if value is None:
        raise RuntimeError(f"discovery availability {key} is malformed")
    try:
        parsed = Decimal(str(value))
    except InvalidOperation as exc:
        raise RuntimeError(f"discovery availability {key} is malformed") from exc
    if not parsed.is_finite() or parsed < 0:
        raise RuntimeError(f"discovery availability {key} is malformed")
    return parsed


def _required_str(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"discovery availability {key} is malformed")
    return value
