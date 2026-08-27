from datetime import UTC, datetime

import pytest

from request_engine.modules.live_capacity.application.recovery_assessment import recovery_pressure
from request_engine.modules.live_capacity.contracts.projection import (
    LiveCapacityProjection,
    ProjectionState,
)

pytestmark = [pytest.mark.unit, pytest.mark.invariant, pytest.mark.capacity]
NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def _projection(
    *,
    operational: int,
    scheduled: int | None,
    live: int | None,
) -> LiveCapacityProjection:
    return LiveCapacityProjection(
        observed_at=NOW,
        state=ProjectionState.KNOWN if live is not None else ProjectionState.PARTIAL,
        reasons=(),
        remaining_operational_seconds=operational,
        projected_remaining_workload_seconds=live,
        projected_end_at=None,
        live_headroom_seconds=None if live is None else operational - live,
        items=(),
        scheduled_committed_workload_seconds=scheduled,
        scheduled_headroom_seconds=None if scheduled is None else operational - scheduled,
    )


def test_recovery_pressure_includes_live_workload_beyond_remaining_day() -> None:
    committed, shortfall, live_pressure = recovery_pressure(
        _projection(operational=6 * 3600, scheduled=6 * 3600, live=7 * 3600)
    )

    assert committed == 6 * 3600
    assert shortfall == 3600
    assert live_pressure == 3600


def test_recovery_pressure_keeps_schedule_shortfall_when_live_projection_unknown() -> None:
    committed, shortfall, live_pressure = recovery_pressure(
        _projection(operational=6 * 3600, scheduled=10 * 3600, live=None)
    )

    assert committed == 10 * 3600
    assert shortfall == 4 * 3600
    assert live_pressure == 0


def test_recovery_pressure_does_not_hide_larger_scheduled_shortfall() -> None:
    committed, shortfall, live_pressure = recovery_pressure(
        _projection(operational=6 * 3600, scheduled=10 * 3600, live=8 * 3600)
    )

    assert committed == 10 * 3600
    assert shortfall == 4 * 3600
    assert live_pressure == 0
