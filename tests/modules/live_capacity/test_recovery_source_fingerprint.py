from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from request_engine.modules.booking.contracts.live_capacity import (
    OperationalAvailabilityInterval,
)
from request_engine.modules.delivery.contracts.live_capacity import (
    ActiveServiceProjectionFact,
    DeliveryProjectionSnapshot,
)
from request_engine.modules.live_capacity.adapters.db.recovery_fingerprint import (
    source_fingerprint,
    source_snapshot,
)
from request_engine.modules.live_capacity.contracts.projection import (
    EstimateSource,
    LiveCapacityProjection,
    ProjectionReason,
    ProjectionState,
    ProjectionWorkItem,
)
from request_engine.modules.queue.contracts.live_capacity import QueueProjectionSnapshot

pytestmark = [pytest.mark.unit, pytest.mark.invariant, pytest.mark.capacity]
NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def _fingerprint(*, active_seconds: int, interrupted: bool = False) -> str:
    work_items = (
        ProjectionWorkItem(
            key=UUID(int=10),
            duration_seconds=3600,
            source=EstimateSource.CONFIGURED_POLICY,
            queue_entry_id=UUID(int=11),
            active_service_seconds=active_seconds,
        ),
    )
    delivery = DeliveryProjectionSnapshot(
        observed_at=NOW,
        active_service=ActiveServiceProjectionFact(
            service_session_id=UUID(int=12),
            queue_entry_id=UUID(int=11),
            resource_id=UUID(int=13),
            location_id=UUID(int=14),
            status="active",
            actual_workload_classification_id=None,
            started_at=NOW - timedelta(minutes=15),
            active_service_seconds=active_seconds,
            has_open_interruption=interrupted,
        ),
        open_resource_activity=None,
    )
    reasons = (ProjectionReason.OPEN_INTERRUPTION,) if interrupted else ()
    projection = LiveCapacityProjection(
        observed_at=NOW,
        state=ProjectionState.PARTIAL if interrupted else ProjectionState.KNOWN,
        reasons=reasons,
        remaining_operational_seconds=7200,
        projected_remaining_workload_seconds=3600 - active_seconds,
        projected_end_at=NOW + timedelta(seconds=3600 - active_seconds),
        live_headroom_seconds=3600 + active_seconds,
        items=(),
        scheduled_committed_workload_seconds=0,
        scheduled_headroom_seconds=7200,
    )
    snapshot = source_snapshot(
        observed_at=NOW,
        horizon_end=NOW + timedelta(hours=2),
        policy_id=UUID(int=1),
        policy_revision=2,
        resource_availability_revision=3,
        location_operational_revision=4,
        recovery_source_revision=5,
        intervals=(OperationalAvailabilityInterval(NOW, NOW + timedelta(hours=2)),),
        planned=(),
        work_items=work_items,
        queue=QueueProjectionSnapshot(queue_id=UUID(int=15), observed_at=NOW, entries=()),
        delivery=delivery,
        projection=projection,
        live_pressure_seconds=0,
    )
    return source_fingerprint(snapshot)


def test_recovery_source_fingerprint_changes_with_live_service_progress() -> None:
    assert _fingerprint(active_seconds=0) != _fingerprint(active_seconds=600)


def test_recovery_source_fingerprint_changes_with_live_blocker() -> None:
    assert _fingerprint(active_seconds=0) != _fingerprint(active_seconds=0, interrupted=True)
