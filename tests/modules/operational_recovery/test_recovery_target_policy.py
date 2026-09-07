from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from request_engine.modules.booking.contracts.appointments import (
    AppointmentSlot,
    ResourceChoice,
)
from request_engine.modules.operational_recovery.application.commands import (
    ExecuteRecoveryCommand,
)
from request_engine.modules.operational_recovery.application.fingerprints import (
    execution_fingerprint,
)
from request_engine.modules.operational_recovery.application.proposal_policy import (
    choose_recovery_target,
)
from request_engine.modules.operational_recovery.contracts.models import RecoveryTarget

pytestmark = [pytest.mark.unit, pytest.mark.invariant, pytest.mark.contract]

NOW = datetime(2026, 8, 26, 13, 0, tzinfo=UTC)


def _slot(identity: int) -> AppointmentSlot:
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
                resource_location_assignment_id=UUID(int=20 + identity),
                assignment_revision=1,
                availability_revision=4,
            ),
        ),
        planned_duration_minutes=60,
        amount=Decimal("3500"),
        currency="DOP",
        location_operational_revision=2,
        configuration_fingerprint=f"sha256:target-{identity}",
    )


def test_recovery_target_skips_original_interval_and_selects_next_slot() -> None:
    original = replace(_slot(1), start_at=NOW, end_at=NOW + timedelta(hours=1))
    next_slot = _slot(2)
    target = choose_recovery_target(
        (original, next_slot),
        original_start=NOW,
        original_end=NOW + timedelta(hours=1),
    )
    assert target is not None
    assert target.start_at == next_slot.start_at
    assert target.configuration_fingerprint == next_slot.configuration_fingerprint


def test_recovery_target_is_none_when_only_original_interval_exists() -> None:
    original = replace(_slot(1), start_at=NOW, end_at=NOW + timedelta(hours=1))
    target = choose_recovery_target(
        (original,),
        original_start=NOW,
        original_end=NOW + timedelta(hours=1),
    )
    assert target is None


def test_execution_replay_fingerprint_is_bound_to_actor_and_idempotency_key() -> None:
    target = RecoveryTarget(
        start_at=NOW + timedelta(hours=2),
        end_at=NOW + timedelta(hours=3),
        location_id=UUID(int=2),
        resources=(
            ResourceChoice(
                UUID(int=3),
                UUID(int=4),
                UUID(int=10),
                1,
                1,
            ),
        ),
        planned_duration_minutes=60,
        amount=Decimal("3500"),
        currency="DOP",
        location_operational_revision=2,
        configuration_fingerprint="sha256:execution-target",
    )
    base = ExecuteRecoveryCommand(
        organization_id=UUID(int=5),
        principal_id=UUID(int=6),
        proposal_id=UUID(int=7),
        reservation_id=UUID(int=8),
        expected_source_fingerprint="source",
        expected_proposal_fingerprint="proposal",
        idempotency_key="key-a",
        allow_subject_override=True,
    )
    other_actor = replace(base, principal_id=UUID(int=9))
    other_key = replace(base, idempotency_key="key-b")
    assert execution_fingerprint(base, target) != execution_fingerprint(other_actor, target)
    assert execution_fingerprint(base, target) != execution_fingerprint(other_key, target)
