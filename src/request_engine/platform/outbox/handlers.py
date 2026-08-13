from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.platform.outbox.worker import OutboxMessageLease


@dataclass(frozen=True, slots=True)
class OutboxEvent:
    message_id: UUID
    organization_id: UUID
    event_type: str
    schema_version: int
    aggregate_kind: str
    aggregate_id: UUID
    payload: dict[str, object]

    @classmethod
    def from_lease(cls, lease: OutboxMessageLease) -> "OutboxEvent":
        return cls(
            message_id=lease.id,
            organization_id=lease.organization_id,
            event_type=lease.event_type,
            schema_version=lease.schema_version,
            aggregate_kind=lease.aggregate_kind,
            aggregate_id=lease.aggregate_id,
            payload=lease.payload,
        )


class OutboxEventHandler(Protocol):
    async def handle(self, event: OutboxEvent) -> None: ...


class UnknownOutboxEvent(Exception):
    pass


class OutboxHandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[tuple[str, int], OutboxEventHandler] = {}

    def register(self, event_type: str, schema_version: int, handler: OutboxEventHandler) -> None:
        if not event_type or schema_version <= 0:
            raise ValueError("event_type and positive schema_version are required")
        key = (event_type, schema_version)
        if key in self._handlers:
            raise ValueError("outbox handler already registered")
        self._handlers[key] = handler

    async def handle_lease(self, lease: OutboxMessageLease) -> None:
        handler = self._handlers.get((lease.event_type, lease.schema_version))
        if handler is None:
            raise UnknownOutboxEvent(
                f"no handler for {lease.event_type!r} version {lease.schema_version}"
            )
        await handler.handle(OutboxEvent.from_lease(lease))

    def registered_keys(self) -> frozenset[tuple[str, int]]:
        return frozenset(self._handlers)
