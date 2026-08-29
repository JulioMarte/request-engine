from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from request_engine.modules.booking.contracts.live_capacity import (
    OperationalAvailabilityInterval,
    PlannedWorkloadFact,
)
from request_engine.modules.live_capacity.application.recovery_policy import (
    affected_recovery_commitments,
)

pytestmark = [pytest.mark.unit, pytest.mark.invariant, pytest.mark.capacity]

NOW = datetime(2026, 8, 26, 13, 0, tzinfo=UTC)


def _planned(identity: int, start_hour: int) -> PlannedWorkloadFact:
    start = NOW.replace(hour=start_hour)
    return PlannedWorkloadFact(
        reservation_id=UUID(int=identity),
        offering_version_id=UUID(int=100 + identity),
        subject_party_id=UUID(int=200 + identity),
        reservation_revision=3,
        planned_starts_at=start,
        planned_ends_at=start + timedelta(hours=1),
        planned_duration_seconds=3600,
    )


def test_structural_shortfall_does_not_mark_still_satisfiable_reservations() -> None:
    closed_commitment = _planned(1, 13)
    satisfiable_commitment = _planned(2, 15)
    remaining = (
        OperationalAvailabilityInterval(
            starts_at=NOW.replace(hour=14),
            ends_at=NOW.replace(hour=17),
        ),
    )

    affected = affected_recovery_commitments(
        (closed_commitment, satisfiable_commitment),
        remaining,
        scheduled_shortfall_seconds=2 * 3600,
    )

    assert [item.reservation_id for item in affected] == [closed_commitment.reservation_id]


def test_live_only_pressure_does_not_fabricate_affected_reservations() -> None:
    first = _planned(1, 14)
    middle = _planned(2, 15)
    latest = _planned(3, 16)
    remaining = (
        OperationalAvailabilityInterval(
            starts_at=NOW,
            ends_at=NOW.replace(hour=17),
        ),
    )

    affected = affected_recovery_commitments(
        (first, middle, latest),
        remaining,
        scheduled_shortfall_seconds=0,
    )

    assert affected == ()


def test_structural_selection_ignores_live_pressure_heuristics() -> None:
    closed = _planned(1, 13)
    latest = _planned(2, 16)
    remaining = (
        OperationalAvailabilityInterval(
            starts_at=NOW.replace(hour=14),
            ends_at=NOW.replace(hour=17),
        ),
    )

    affected = affected_recovery_commitments(
        (closed, latest),
        remaining,
        scheduled_shortfall_seconds=3600,
    )

    assert [item.reservation_id for item in affected] == [closed.reservation_id]
