from datetime import UTC, datetime, timedelta
from uuid import UUID

from request_engine.modules.booking.contracts.live_capacity import (
    OperationalAvailabilityInterval,
    PlannedWorkloadFact,
)
from request_engine.modules.live_capacity.application.recovery_policy import (
    affected_recovery_commitments,
)

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def _planned(identity: int, *, hour: int) -> PlannedWorkloadFact:
    start = NOW + timedelta(hours=hour)
    return PlannedWorkloadFact(
        reservation_id=UUID(int=identity),
        offering_version_id=UUID(int=100),
        subject_party_id=UUID(int=200 + identity),
        reservation_revision=1,
        planned_starts_at=start,
        planned_ends_at=start + timedelta(hours=1),
        planned_duration_seconds=3600,
    )


def test_live_pressure_never_fabricates_affected_reservations() -> None:
    planned = tuple(_planned(i + 1, hour=i) for i in range(4))
    interval = OperationalAvailabilityInterval(
        starts_at=NOW,
        ends_at=NOW + timedelta(hours=4),
    )

    affected = affected_recovery_commitments(
        planned,
        (interval,),
        scheduled_shortfall_seconds=0,
    )

    assert affected == ()


def test_only_reservations_outside_authoritative_interval_are_affected() -> None:
    planned = tuple(_planned(i + 1, hour=i) for i in range(10))
    interval = OperationalAvailabilityInterval(
        starts_at=NOW,
        ends_at=NOW + timedelta(hours=6),
    )

    affected = affected_recovery_commitments(
        planned,
        (interval,),
        scheduled_shortfall_seconds=4 * 3600,
    )

    assert tuple(item.reservation_id for item in affected) == tuple(
        UUID(int=i) for i in range(7, 11)
    )
