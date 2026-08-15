from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Protocol, cast
from uuid import UUID

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


@dataclass(frozen=True, slots=True)
class OutboxEvent:
    id: UUID
    organization_id: UUID
    event_type: str
    schema_version: int
    aggregate_kind: str | None
    aggregate_id: UUID | None
    payload: dict[str, object]


class OutboxPublisher(Protocol):
    async def publish(self, event: OutboxEvent) -> None: ...


OutboxInternalHandler = Callable[[OutboxEvent], Awaitable[None]]


class OutboxPipelineProcessor:
    """Run idempotent local consequences, then publish the durable event.

    The Outbox lease is completed only after both phases succeed. If the process
    crashes between them, the local handler is replayed and therefore must use
    the OutboxMessage id as its idempotency/source-event identity.
    """

    def __init__(
        self,
        *,
        publisher: OutboxPublisher,
        internal_handlers: Mapping[str, OutboxInternalHandler] | None = None,
    ) -> None:
        self._publisher = publisher
        self._internal_handlers = dict(internal_handlers or {})

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
        handler = self._internal_handlers.get(event.event_type)
        if handler is not None:
            await handler(event)
        await self._publisher.publish(event)


class ReservationLifecycleOutboxHandler:
    """Bridge Reservation outbox facts into the Phase 3 idempotent lifecycle composition."""

    _EVENT_TYPES = {
        "reservation.created.v1",
        "reservation.rescheduled.v1",
        "reservation.cancelled.v1",
    }

    def __init__(
        self,
        *,
        worker_principal_id: UUID,
        reader: ReservationLifecycleReader,
        scheduling: ReservationLifecycleSchedulingPort,
        notifications: ReservationLifecycleNotificationPort,
        recovery: ReleasedSlotRecoveryPort,
    ) -> None:
        self._worker_principal_id = worker_principal_id
        self._reader = reader
        self._scheduling = scheduling
        self._notifications = notifications
        self._recovery = recovery

    async def handle(self, event: OutboxEvent) -> None:
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

        await handle_reservation_lifecycle_event(
            ReservationLifecycleEvent(
                event_id=event.id,
                organization_id=event.organization_id,
                reservation_id=event.aggregate_id,
                event_type=cast(ReservationEventType, event.event_type),
            ),
            worker_principal_id=self._worker_principal_id,
            reader=self._reader,
            scheduling=self._scheduling,
            notifications=self._notifications,
            recovery=self._recovery,
        )

    def handlers(self) -> dict[str, OutboxInternalHandler]:
        return {event_type: self.handle for event_type in self._EVENT_TYPES}
