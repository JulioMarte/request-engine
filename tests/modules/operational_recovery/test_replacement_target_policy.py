from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
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


def _same_time_slot(resource_id: int) -> AppointmentSlot:
    return AppointmentSlot(
        offering_version_id=UUID(int=1),
        start_at=NOW,
        end_at=NOW + timedelta(hours=1),
        location_id=UUID(int=2),
        resources=(
            ResourceChoice(
                requirement_id=UUID(int=3),
                resource_id=UUID(int=resource_id),
                resource_location_assignment_id=UUID(int=100 + resource_id),
                assignment_revision=1,
                availability_revision=4,
            ),
        ),
        planned_duration_minutes=60,
        amount=Decimal("3500"),
        currency="DOP",
        location_operational_revision=2,
        configuration_fingerprint=f"sha256:replacement-{resource_id}",
    )


def test_replacement_keeps_time_and_changes_degraded_resource() -> None:
    degraded = _same_time_slot(10)
    alternate = _same_time_slot(11)
    target = choose_replacement_target(
        (degraded, alternate),
        original_start=NOW,
        original_end=NOW + timedelta(hours=1),
        source_resource_id=UUID(int=10),
    )
    assert target is not None
    assert target.actionable is True
    assert target.start_at == NOW
    assert target.end_at == NOW + timedelta(hours=1)
    assert target.resources[0].resource_id == UUID(int=11)


def test_replacement_does_not_relabel_reschedule() -> None:
    later = replace(
        _same_time_slot(11),
        start_at=NOW + timedelta(hours=2),
        end_at=NOW + timedelta(hours=3),
    )
    target = choose_replacement_target(
        (later,),
        original_start=NOW,
        original_end=NOW + timedelta(hours=1),
        source_resource_id=UUID(int=10),
    )
    assert target is None


def test_replacement_is_none_when_only_degraded_resource_is_available() -> None:
    degraded = _same_time_slot(10)
    target = choose_replacement_target(
        (degraded,),
        original_start=NOW,
        original_end=NOW + timedelta(hours=1),
        source_resource_id=UUID(int=10),
    )
    assert target is None
