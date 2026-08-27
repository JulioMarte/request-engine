from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from request_engine.modules.booking.contracts.live_capacity import (
    OperationalAvailabilityInterval,
)
from request_engine.modules.live_capacity.adapters.db.recovery_fingerprint import (
    source_fingerprint,
)
from request_engine.modules.live_capacity.contracts.projection import (
    EstimateSource,
    ProjectionWorkItem,
)

pytestmark = [pytest.mark.unit, pytest.mark.invariant, pytest.mark.capacity]
NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def _fingerprint(*, active_seconds: int, interrupted: bool = False) -> str:
    return source_fingerprint(
        policy_id=UUID(int=1),
        policy_revision=2,
        resource_availability_revision=3,
        location_operational_revision=4,
        intervals=(OperationalAvailabilityInterval(NOW, NOW + timedelta(hours=2)),),
        planned=(),
        work_items=(
            ProjectionWorkItem(
                key=UUID(int=10),
                duration_seconds=3600,
                source=EstimateSource.CONFIGURED_POLICY,
                queue_entry_id=UUID(int=11),
                active_service_seconds=active_seconds,
            ),
        ),
        has_open_interruption=interrupted,
        has_open_resource_activity=False,
    )


def test_recovery_source_fingerprint_changes_with_live_service_progress() -> None:
    assert _fingerprint(active_seconds=0) != _fingerprint(active_seconds=600)


def test_recovery_source_fingerprint_changes_with_live_blocker() -> None:
    assert _fingerprint(active_seconds=0) != _fingerprint(active_seconds=0, interrupted=True)
