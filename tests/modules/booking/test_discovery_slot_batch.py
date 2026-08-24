import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from request_engine.modules.booking.adapters.discovery_slot_reader import (
    PostgresPublishedSlotReader,
)
from request_engine.modules.booking.contracts.appointments import AppointmentSlot
from request_engine.modules.booking.contracts.discovery import PublishedSlotQuery

NOW = datetime(2035, 1, 1, tzinfo=UTC)


class ConcurrencyProbe(PostgresPublishedSlotReader):
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0

    async def find_published_slots(
        self, query: PublishedSlotQuery
    ) -> tuple[AppointmentSlot, ...]:
        del query
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        return ()


def query() -> PublishedSlotQuery:
    return PublishedSlotQuery(
        organization_id=uuid4(),
        publication_id=uuid4(),
        publication_revision=1,
        mapping_id=uuid4(),
        mapping_revision=1,
        offering_version_id=uuid4(),
        window_start=NOW,
        window_end=NOW + timedelta(hours=1),
        location_id=uuid4(),
        limit=10,
    )


@pytest.mark.asyncio
async def test_batch_parallelism_is_bounded_but_not_serial() -> None:
    reader = ConcurrencyProbe()
    groups = await reader.find_published_slots_batch(tuple(query() for _ in range(24)))

    assert groups == tuple(() for _ in range(24))
    assert 1 < reader.max_active <= 8
