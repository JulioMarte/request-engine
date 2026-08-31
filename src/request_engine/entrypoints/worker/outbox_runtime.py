from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, cast, runtime_checkable
from uuid import UUID

import request_engine.modules.delivery.contracts.access as delivery_access
from request_engine.entrypoints.worker.reservation_lifecycle import (
    ReservationEventType,
    ReservationLifecycleEvent,
    handle_reservation_lifecycle_event,
)
from request_engine.modules.booking.contracts.lifecycle import (
    ReservationLifecycleReader,
    ReservationLifecycleSchedulingPort,
)
from request_engine.modules.communications.contracts.reservation_lifecycle import (
    ReservationLifecycleNotificationPort,
)
from request_engine.modules.queue.contracts.released_slot_recovery import ReleasedSlotRecoveryPort
from request_engine.platform.outbox.worker import OutboxLease
from request_engine.platform.worker.runtime import PermanentWorkError

RESERVATION_LIFECYCLE_EVENT_TYPES = frozenset(
    {
        "reservation.created.v1",
        "reservation.rescheduled.v1",
        "reservation.cancelled.v1",
    }
)


@dataclass(frozen=True, slots=True)
class OutboxEvent:
    id: UUID
    organization_id: UUID
    event_type: str
    schema_version: int
    aggregate_kind: str | None
    aggregate_id: UUID | None
    payload: dict[str, object]


@runtime_checkable
class OutboxPublisher(Protocol):
    async def publish(self, event: OutboxEvent) -> None: ...


OutboxInternalHandler = Callable[[OutboxEvent], Awaitable[None]]
FencedOutboxInternalHandler = Callable[[OutboxEvent, UUID], Awaitable[None]]


class OutboxPipelineProcessor:
    """Run local consequences, then publish a capability-token-free event.

    Technical Outbox claim tokens are passed only to handlers that explicitly
    request a fenced local execution surface. They are never placed on
    ``OutboxEvent`` and therefore cannot leak to integration publishers.
    """

    def __init__(
        self,
        *,
        publisher: OutboxPublisher,
        internal_handlers: Mapping[str, OutboxInternalHandler] | None = None,
        fenced_internal_handlers: Mapping[str, FencedOutboxInternalHandler] | None = None,
    ) -> None:
        self._publisher = publisher
        self._internal_handlers = dict(internal_handlers or {})
        self._fenced_internal_handlers = dict(fenced_internal_handlers or {})
        overlap = self._internal_handlers.keys() & self._fenced_internal_handlers.keys()
        if overlap:
            names = ", ".join(sorted(overlap))
            raise ValueError(f"Outbox event types registered twice: {names}")

    async def process(self, lease: OutboxLease) -> None:
        event = OutboxEvent(
            id=lease.id,
            organization_id=lease.organization_id,
            event_type=lease.event_type,
            schema_version=lease.schema_version,
            aggregate_kind=lease.aggregate_kind,
            aggregate_id=lease.aggregate_id,
            payload=lease.payload,
        )
        fenced_handler = self._fenced_internal_handlers.get(event.event_type)
        if fenced_handler is not None:
            await fenced_handler(event, lease.claim_token)
        else:
            handler = self._internal_handlers.get(event.event_type)
            if handler is not None:
                await handler(event)
        await self._publisher.publish(event)


class ReservationLifecycleOutboxHandler:
    """Bridge Reservation facts into lifecycle composition under one Outbox claim."""

    _EVENT_TYPES = RESERVATION_LIFECYCLE_EVENT_TYPES

    def __init__(
        self,
        *,
        worker_principal_id: UUID,
        reader: ReservationLifecycleReader,
        scheduling: ReservationLifecycleSchedulingPort,
        notifications: ReservationLifecycleNotificationPort,
        recovery: ReleasedSlotRecoveryPort,
        reservation_access: delivery_access.ReservationAccessLifecyclePort | None = None,
    ) -> None:
        self._worker_principal_id = worker_principal_id
        self._reader = reader
        self._scheduling = scheduling
        self._notifications = notifications
        self._recovery = recovery
        self._reservation_access = reservation_access

    async def handle(self, event: OutboxEvent, claim_token: UUID) -> None:
        if event.event_type not in self._EVENT_TYPES:
            raise PermanentWorkError("unsupported_reservation_lifecycle_event")
        if event.schema_version != 1:
            raise PermanentWorkError("unsupported_reservation_lifecycle_event_version")
        if event.aggregate_kind != "Reservation" or event.aggregate_id is None:
            raise PermanentWorkError("reservation_lifecycle_event_shape_invalid")
        raw_reservation_id = event.payload.get("reservation_id")
        if raw_reservation_id is not None:
            if not isinstance(raw_reservation_id, str):
                raise PermanentWorkError("reservation_lifecycle_payload_invalid")
            try:
                payload_reservation_id = UUID(raw_reservation_id)
            except ValueError as exc:
                raise PermanentWorkError("reservation_lifecycle_payload_invalid") from exc
            if payload_reservation_id != event.aggregate_id:
                raise PermanentWorkError("reservation_lifecycle_payload_mismatch")

        released_start_at: datetime | None = None
        released_end_at: datetime | None = None
        released_location_id: UUID | None = None
        if event.event_type == "reservation.rescheduled.v1":
            released_start_at, released_end_at, released_location_id = (
                _parse_reschedule_release_payload(event.payload)
            )

        await handle_reservation_lifecycle_event(
            ReservationLifecycleEvent(
                event_id=event.id,
                organization_id=event.organization_id,
                reservation_id=event.aggregate_id,
                event_type=cast(ReservationEventType, event.event_type),
                released_start_at=released_start_at,
                released_end_at=released_end_at,
                released_location_id=released_location_id,
            ),
            worker_principal_id=self._worker_principal_id,
            reader=self._reader,
            scheduling=self._scheduling,
            notifications=self._notifications,
            recovery=self._recovery,
            reservation_access=self._reservation_access,
            delivery_work_claim=delivery_access.DeliveryWorkClaim(
                organization_id=event.organization_id,
                message_id=event.id,
                claim_token=claim_token,
            ),
        )

    def handlers(self) -> dict[str, FencedOutboxInternalHandler]:
        return {event_type: self.handle for event_type in self._EVENT_TYPES}


def _parse_reschedule_release_payload(
    payload: dict[str, object],
) -> tuple[datetime, datetime, UUID | None]:
    raw_start = payload.get("old_start_at")
    raw_end = payload.get("old_end_at")
    raw_location = payload.get("old_location_id")
    if not isinstance(raw_start, str) or not isinstance(raw_end, str):
        raise PermanentWorkError("reservation_lifecycle_payload_invalid")
    try:
        start_at = datetime.fromisoformat(raw_start)
        end_at = datetime.fromisoformat(raw_end)
    except ValueError as exc:
        raise PermanentWorkError("reservation_lifecycle_payload_invalid") from exc
    if start_at.utcoffset() is None or end_at.utcoffset() is None or end_at <= start_at:
        raise PermanentWorkError("reservation_lifecycle_payload_invalid")

    if raw_location is None:
        location_id = None
    elif isinstance(raw_location, str):
        try:
            location_id = UUID(raw_location)
        except ValueError as exc:
            raise PermanentWorkError("reservation_lifecycle_payload_invalid") from exc
    else:
        raise PermanentWorkError("reservation_lifecycle_payload_invalid")
    return start_at, end_at, location_id
