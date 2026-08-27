from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from request_engine.modules.booking.contracts.appointments import AppointmentSlot, ResourceChoice
from request_engine.modules.operational_recovery.application.service import _choose_target

pytestmark = [pytest.mark.unit, pytest.mark.invariant, pytest.mark.contract]

NOW = datetime(2026, 8, 26, 13, 0, tzinfo=UTC)


def _slot(identity: int, *, contextual: bool) -> AppointmentSlot:
    start = NOW + timedelta(hours=identity)
    return AppointmentSlot(
        offering_version_id=UUID(int=1),
        start_at=start,
        end_at=start + timedelta(hours=1),
        location_id=UUID(int=2),
        resources=(
            ResourceChoice(
                requirement_id=UUID(int=3),
                resource_id=UUID(int=10 + identity),
                resource_location_assignment_id=(UUID(int=20 + identity) if contextual else None),
                assignment_revision=1 if contextual else None,
                availability_revision=4,
            ),
        ),
    )


def test_legacy_source_skips_blocked_contextual_target_for_later_actionable_slot() -> None:
    contextual = _slot(1, contextual=True)
    legacy = _slot(2, contextual=False)

    target = _choose_target(
        (contextual, legacy),
        original_start=NOW,
        original_end=NOW + timedelta(hours=1),
        source_contextual=False,
    )

    assert target is not None
    assert target.actionable is True
    assert target.start_at == legacy.start_at


def test_contextual_source_never_becomes_actionable_through_legacy_target() -> None:
    legacy = _slot(1, contextual=False)

    target = _choose_target(
        (legacy,),
        original_start=NOW,
        original_end=NOW + timedelta(hours=1),
        source_contextual=True,
    )

    assert target is not None
    assert target.actionable is False
    assert target.blocked_reason == "contextual_source_reschedule_not_supported"
