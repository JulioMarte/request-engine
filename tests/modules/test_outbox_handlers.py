from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from request_engine.platform.outbox.handlers import (
    OutboxEvent,
    OutboxHandlerRegistry,
    UnknownOutboxEvent,
)
from request_engine.platform.outbox.worker import OutboxMessageLease


@dataclass
class RecordingHandler:
    seen: list[OutboxEvent]

    async def handle(self, event: OutboxEvent) -> None:
        self.seen.append(event)


def _lease(*, event_type: str = "reservation.cancelled.v1", version: int = 1) -> OutboxMessageLease:
    now = datetime.now(UTC)
    return OutboxMessageLease(
        id=uuid4(),
        organization_id=uuid4(),
        claim_token=uuid4(),
        event_type=event_type,
        schema_version=version,
        aggregate_kind="Reservation",
        aggregate_id=uuid4(),
        payload={"reservation_id": str(uuid4())},
        attempt_count=1,
        lease_until=now,
    )


@pytest.mark.asyncio
async def test_outbox_handler_registry_requires_exact_event_version() -> None:
    seen: list[OutboxEvent] = []
    registry = OutboxHandlerRegistry()
    registry.register("reservation.cancelled.v1", 1, RecordingHandler(seen))

    lease = _lease()
    await registry.handle_lease(lease)
    assert len(seen) == 1
    assert seen[0].message_id == lease.id
    assert seen[0].organization_id == lease.organization_id

    with pytest.raises(UnknownOutboxEvent):
        await registry.handle_lease(_lease(version=2))


def test_outbox_handler_registry_rejects_duplicate_registration() -> None:
    registry = OutboxHandlerRegistry()
    handler = RecordingHandler([])
    registry.register("reservation.cancelled.v1", 1, handler)
    with pytest.raises(ValueError, match="already registered"):
        registry.register("reservation.cancelled.v1", 1, handler)
