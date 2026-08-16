from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from request_engine.entrypoints.worker.outbox_runtime import (
    OutboxEvent,
    OutboxPipelineProcessor,
)
from request_engine.platform.outbox.worker import OutboxLease


class _Publisher:
    def __init__(self) -> None:
        self.events: list[OutboxEvent] = []

    async def publish(self, event: OutboxEvent) -> None:
        self.events.append(event)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_fenced_outbox_handler_receives_token_without_publisher_leak() -> None:
    publisher = _Publisher()
    captured: list[UUID] = []

    async def fenced_handler(event: OutboxEvent, claim_token: UUID) -> None:
        assert event.event_type == "reservation.created.v1"
        captured.append(claim_token)

    processor = OutboxPipelineProcessor(
        publisher=publisher,
        fenced_internal_handlers={"reservation.created.v1": fenced_handler},
    )
    token = uuid4()
    lease = OutboxLease(
        id=uuid4(),
        organization_id=uuid4(),
        claim_token=token,
        event_type="reservation.created.v1",
        schema_version=1,
        aggregate_kind="Reservation",
        aggregate_id=uuid4(),
        payload={},
        attempt_count=1,
        lease_until=datetime.now(UTC),
    )

    await processor.process(lease)

    assert captured == [token]
    assert len(publisher.events) == 1
    assert not hasattr(publisher.events[0], "claim_token")


@pytest.mark.unit
def test_outbox_processor_rejects_duplicate_fenced_and_unfenced_registration() -> None:
    async def normal(event: OutboxEvent) -> None:
        del event

    async def fenced(event: OutboxEvent, claim_token: UUID) -> None:
        del event, claim_token

    with pytest.raises(ValueError, match="registered twice"):
        OutboxPipelineProcessor(
            publisher=_Publisher(),
            internal_handlers={"reservation.created.v1": normal},
            fenced_internal_handlers={"reservation.created.v1": fenced},
        )
