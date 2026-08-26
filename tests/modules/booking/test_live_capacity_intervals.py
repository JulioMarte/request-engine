from datetime import UTC, date, datetime, time, timedelta

import pytest

from request_engine.modules.booking.adapters.db.live_capacity_intervals import (
    effective_operational_intervals,
)
from request_engine.modules.booking.domain.availability import (
    AvailabilityException,
    CapacityModel,
    ExceptionKind,
    LiveCapacityClaim,
    RecurringAvailability,
    ResourceAvailability,
)

pytestmark = [pytest.mark.unit, pytest.mark.temporal]

NOW = datetime(2026, 8, 26, 14, 0, tzinfo=UTC)


def _profile(
    *,
    exceptions: tuple[AvailabilityException, ...] = (),
    claims: tuple[LiveCapacityClaim, ...] = (),
) -> ResourceAvailability:
    return ResourceAvailability(
        capacity_model=CapacityModel.EXCLUSIVE,
        capacity_units=1,
        default_timezone="UTC",
        schedules=(
            RecurringAvailability(
                weekday=NOW.weekday(),
                local_start=time(13, 0),
                local_end=time(18, 0),
                timezone="UTC",
                valid_from=date(2026, 1, 1),
                valid_until=None,
            ),
        ),
        exceptions=exceptions,
        live_claims=claims,
    )


def test_unavailable_exception_creates_discontinuous_projection_intervals() -> None:
    result = effective_operational_intervals(
        profiles=(
            _profile(
                exceptions=(
                    AvailabilityException(
                        NOW + timedelta(hours=1),
                        NOW + timedelta(hours=2),
                        ExceptionKind.UNAVAILABLE,
                    ),
                )
            ),
        ),
        observed_at=NOW,
        horizon_end=NOW + timedelta(hours=4),
    )

    assert tuple((item.starts_at, item.ends_at) for item in result) == (
        (NOW, NOW + timedelta(hours=1)),
        (NOW + timedelta(hours=2), NOW + timedelta(hours=4)),
    )


def test_opaque_hold_removes_interval_without_reservation_workload_double_count() -> None:
    result = effective_operational_intervals(
        profiles=(
            _profile(
                claims=(
                    LiveCapacityClaim(
                        NOW + timedelta(minutes=30),
                        NOW + timedelta(minutes=60),
                        1,
                    ),
                )
            ),
        ),
        observed_at=NOW,
        horizon_end=NOW + timedelta(hours=2),
    )

    assert tuple((item.starts_at, item.ends_at) for item in result) == (
        (NOW, NOW + timedelta(minutes=30)),
        (NOW + timedelta(minutes=60), NOW + timedelta(hours=2)),
    )
