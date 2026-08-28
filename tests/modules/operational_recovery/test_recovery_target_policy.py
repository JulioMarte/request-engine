from dataclasses import replace
from datetime import UTC, datetime, timedelta
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
    choose_replacement_target,
)
from request_engine.modules.operational_recovery.contracts.models import RecoveryTarget

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


def _same_time_slot(resource_id: int, *, contextual: bool) -> AppointmentSlot:
    return replace(
        _slot(0, contextual=contextual),
        resources=(
            ResourceChoice(
                requirement_id=UUID(int=3),
                resource_id=UUID(int=resource_id),
                resource_location_assignment_id=(UUID(int=100 + resource_id) if contextual else None),
                assignment_revision=1 if contextual else None,
                availability_revision=4,
            ),
        ),
    )


def test_legacy_source_skips_contextual_target_for_legacy_slot() -> None:
    contextual = _slot(1, contextual=True)
    legacy = _slot(2, contextual=False)
    target = choose_recovery_target(
        (contextual, legacy),
        original_start=NOW,
        original_end=NOW + timedelta(hours=1),
        source_contextual=False,
    )
    assert target is not None
    assert target.actionable is True
    assert target.start_at == legacy.start_at


def test_contextual_source_selects_contextual_target() -> None:
    legacy = _slot(1, contextual=False)
    contextual = _slot(2, contextual=True)
    target = choose_recovery_target(
        (legacy, contextual),
        original_start=NOW,
        original_end=NOW + timedelta(hours=1),
        source_contextual=True,
    )
    assert target is not None
    assert target.actionable is True
    assert target.start_at == contextual.start_at
    assert target.blocked_reason is None


def test_contextual_source_fails_closed_when_only_legacy_target_exists() -> None:
    target = choose_recovery_target(
        (_slot(1, contextual=False),),
        original_start=NOW,
        original_end=NOW + timedelta(hours=1),
        source_contextual=True,
    )
    assert target is not None
    assert target.actionable is False
    assert target.blocked_reason == "contextual_source_requires_contextual_target"


def test_replacement_target_keeps_time_and_changes_degraded_resource() -> None:
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


def test_replacement_target_does_not_relabel_reschedule_as_replacement() -> None:
    later = _slot(2, contextual=True)
    target = choose_replacement_target(
        (later,),
        original_start=NOW,
        original_end=NOW + timedelta(hours=1),
        source_resource_id=UUID(int=10),
        source_contextual=True,
    )
    assert target is None


def test_replacement_target_fails_closed_across_context_boundary() -> None:
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


def test_execution_replay_fingerprint_is_bound_to_actor_and_idempotency_key() -> None:
    target = RecoveryTarget(
        start_at=NOW + timedelta(hours=2),
        end_at=NOW + timedelta(hours=3),
        location_id=UUID(int=2),
        resources=(ResourceChoice(UUID(int=3), UUID(int=4)),),
        actionable=True,
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
