from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from request_engine.modules.booking.contracts.live_capacity import PlannedWorkloadFact
from request_engine.modules.delivery.contracts.live_capacity import DeliveryProjectionSnapshot
from request_engine.modules.live_capacity.application.workload_builder import (
    build_remaining_work,
    scheduled_work,
)
from request_engine.modules.queue.contracts.live_capacity import QueueProjectionSnapshot

pytestmark = [
    pytest.mark.unit,
    pytest.mark.invariant,
    pytest.mark.contract,
    pytest.mark.adversarial,
    pytest.mark.capacity,
    pytest.mark.provenance,
]

NOW = datetime(2026, 8, 26, 14, 0, tzinfo=UTC)


def test_completed_early_reservation_stays_scheduled_but_not_live_work() -> None:
    reservation_id = UUID(int=101)
    planned = (
        PlannedWorkloadFact(
            reservation_id=reservation_id,
            offering_version_id=UUID(int=102),
            planned_starts_at=NOW + timedelta(minutes=30),
            planned_ends_at=NOW + timedelta(minutes=60),
            planned_duration_seconds=30 * 60,
        ),
    )
    queue = QueueProjectionSnapshot(
        queue_id=UUID(int=103),
        observed_at=NOW,
        entries=(),
        completed_reservation_ids=frozenset({reservation_id}),
    )

    live = build_remaining_work(
        queue=queue,
        delivery=DeliveryProjectionSnapshot(NOW, None, None),
        planned=planned,
        estimates={},
    )

    assert live == ()
    scheduled = scheduled_work(planned)
    assert len(scheduled) == 1
    assert scheduled[0].reservation_id == reservation_id
    assert scheduled[0].duration_seconds == 30 * 60
