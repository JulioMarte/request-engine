from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from request_engine.modules.booking.contracts.live_capacity import (
    OperationalAvailabilityInterval,
    PlannedWorkloadFact,
)
from request_engine.modules.live_capacity.adapters.db.recovery_source import (
    _affected_commitments,
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


def test_shortfall_does_not_fill_affected_set_with_still_satisfiable_reservations() -> None:
    closed_commitment = _planned(1, 13)
    satisfiable_commitment = _planned(2, 15)
    remaining = (
        OperationalAvailabilityInterval(
            starts_at=NOW.replace(hour=14),
            ends_at=NOW.replace(hour=17),
        ),
    )

    affected = _affected_commitments(
        (closed_commitment, satisfiable_commitment),
        remaining,
        shortfall=2 * 3600,
    )

    assert [item.reservation_id for item in affected] == [closed_commitment.reservation_id]
