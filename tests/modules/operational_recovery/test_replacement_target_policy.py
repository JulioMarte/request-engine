from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from request_engine.modules.booking.contracts.appointments import (
    AppointmentSlot,
    ResourceChoice,
)
from request_engine.modules.operational_recovery.application.proposal_policy import (
    choose_replacement_target,
)

pytestmark = [pytest.mark.unit, pytest.mark.invariant, pytest.mark.contract]

NOW = datetime(2026, 8, 26, 13, 0, tzinfo=UTC)


def _same_time_slot(resource_id: int, *, contextual: bool) -> AppointmentSlot:
    base = AppointmentSlot(
        offering_version_id=UUID(int=1),
        start_at=NOW,
        end_at=NOW + timedelta(hours=1),
        location_id=UUID(int=2),
        resources=(),
    )
    assignment_id = UUID(int=100 + resource_id) if contextual else None
    return replace(
        base,
        resources=(
            ResourceChoice(
                requirement_id=UUID(int=3),
                resource_id=UUID(int=resource_id),
                resource_location_assignment_id=assignment_id,
                assignment_revision=1 if contextual else None,
                availability_revision=4,
            ),
        ),
    )


def test_replacement_keeps_time_and_changes_degraded_resource() -> None:
    degraded = _same_time_slot(10, contextual=True)
    alternate = _same_time_slot(11, contextual=True)
    target = choose_replacement_target(
        (degraded, alternate),
        original_start=NOW,
        original_end=NOW + timedelta(hours=1),
        source_resource_id=UUID(int=10),
        source_contextual=True,
    )
    assert target is not None
    assert target.actionable is True
    assert target.start_at == NOW
    assert target.end_at == NOW + timedelta(hours=1)
    assert target.resources[0].resource_id == UUID(int=11)


def test_replacement_does_not_relabel_reschedule() -> None:
    later = replace(
        _same_time_slot(11, contextual=True),
        start_at=NOW + timedelta(hours=2),
        end_at=NOW + timedelta(hours=3),
    )
    target = choose_replacement_target(
        (later,),
        original_start=NOW,
        original_end=NOW + timedelta(hours=1),
        source_resource_id=UUID(int=10),
        source_contextual=True,
    )
    assert target is None


def test_replacement_fails_closed_across_context_boundary() -> None:
    legacy = _same_time_slot(11, contextual=False)
    target = choose_replacement_target(
        (legacy,),
        original_start=NOW,
        original_end=NOW + timedelta(hours=1),
        source_resource_id=UUID(int=10),
        source_contextual=True,
    )
    assert target is not None
    assert target.actionable is False
    assert target.blocked_reason == "contextual_source_requires_contextual_target"
