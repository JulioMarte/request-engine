from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from request_engine.modules.booking.contracts.live_capacity import PlannedWorkloadFact
from request_engine.modules.delivery.contracts.live_capacity import DeliveryProjectionSnapshot
from request_engine.modules.live_capacity.application.workload_builder import build_remaining_work
from request_engine.modules.live_capacity.contracts.projection import EstimateSource
from request_engine.modules.queue.contracts.live_capacity import (
    QueueProjectionEntry,
    QueueProjectionSnapshot,
)

pytestmark = [pytest.mark.unit, pytest.mark.contract]

NOW = datetime(2026, 8, 26, 14, 0, tzinfo=UTC)


def test_reservation_planned_duration_follows_queue_entry_after_dedup() -> None:
    reservation_id = UUID(int=1)
    queue_entry_id = UUID(int=2)
    workload_id = UUID(int=3)
    planned = (
        PlannedWorkloadFact(
            reservation_id=reservation_id,
            offering_version_id=UUID(int=4),
            planned_starts_at=NOW,
            planned_ends_at=NOW + timedelta(minutes=30),
            planned_duration_seconds=30 * 60,
        ),
    )
    queue = QueueProjectionSnapshot(
        queue_id=UUID(int=5),
        observed_at=NOW,
        entries=(
            QueueProjectionEntry(
                queue_entry_id=queue_entry_id,
                queue_id=UUID(int=5),
                reservation_id=reservation_id,
                status="waiting",
                arrived_at=NOW,
                admitted_at=NOW,
                called_at=None,
                expected_workload_classification_id=workload_id,
            ),
        ),
    )
    delivery = DeliveryProjectionSnapshot(NOW, None, None)

    result = build_remaining_work(
        queue=queue,
        delivery=delivery,
        planned=planned,
        estimates={},
    )

    assert len(result) == 1
    assert result[0].key == queue_entry_id
    assert result[0].reservation_id == reservation_id
    assert result[0].duration_seconds == 30 * 60
    assert result[0].source is EstimateSource.PLANNED_DURATION


def test_configured_estimate_still_precedes_planned_duration() -> None:
    from request_engine.modules.live_capacity.contracts.projection import WorkloadEstimate

    reservation_id = UUID(int=11)
    workload_id = UUID(int=12)
    planned = (
        PlannedWorkloadFact(
            reservation_id,
            UUID(int=13),
            NOW,
            NOW + timedelta(minutes=30),
            30 * 60,
        ),
    )
    queue = QueueProjectionSnapshot(
        UUID(int=14),
        NOW,
        (
            QueueProjectionEntry(
                UUID(int=15),
                UUID(int=14),
                reservation_id,
                "waiting",
                NOW,
                NOW,
                None,
                workload_id,
            ),
        ),
    )

    result = build_remaining_work(
        queue=queue,
        delivery=DeliveryProjectionSnapshot(NOW, None, None),
        planned=planned,
        estimates={workload_id: WorkloadEstimate(20 * 60, EstimateSource.CONFIGURED_POLICY)},
    )

    assert result[0].duration_seconds == 20 * 60
    assert result[0].source is EstimateSource.CONFIGURED_POLICY
