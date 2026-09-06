from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol
from uuid import UUID

from request_engine.modules.operational_recovery.contracts.models import (
    AffectedReservation,
    RescheduleProposal,
)


@dataclass(frozen=True, slots=True)
class RecoveryAutonomyPolicy:
    organization_id: UUID
    service_queue_id: UUID
    enabled: bool
    max_delay_minutes: int
    max_auto_actions_per_incident: int
    granted_by: UUID


@dataclass(frozen=True, slots=True)
class ConfigureRecoveryAutonomyCommand:
    organization_id: UUID
    principal_id: UUID
    service_queue_id: UUID
    enabled: bool
    max_delay_minutes: int
    max_auto_actions_per_incident: int
    idempotency_key: str


def autonomy_reschedule_key(incident_id: UUID, reservation_id: UUID, source_revision: int) -> str:
    return f"recovery-auto:{incident_id}:{reservation_id}:{source_revision}:v1"


class RecoveryAutonomyConfiguration(Protocol):
    async def configure(
        self, command: ConfigureRecoveryAutonomyCommand
    ) -> RecoveryAutonomyPolicy: ...


class RecoveryAutonomyPolicyReader(Protocol):
    async def active_policy(
        self, *, organization_id: UUID, service_queue_id: UUID
    ) -> RecoveryAutonomyPolicy | None: ...

    async def autonomous_attempt_keys(
        self, *, organization_id: UUID, incident_id: UUID
    ) -> frozenset[str]: ...


def reschedule_within_envelope(
    policy: RecoveryAutonomyPolicy,
    proposal: RescheduleProposal,
    affected: AffectedReservation,
) -> bool:
    """Contract 32 section 14: the operator-granted autonomy envelope.

    Autonomy never chooses targets; it may only execute the persisted proposal's
    own reschedule candidate, strictly later, within the granted delay budget.
    The reservation keeps its subject; target slots stay inside the proposal's
    location-bound search.
    """

    target = affected.target
    if target is None:
        return False
    delay = target.start_at - affected.original_start_at
    if delay <= timedelta(0):
        return False
    return delay <= timedelta(minutes=policy.max_delay_minutes)


def autonomous_execution_plan(
    policy: RecoveryAutonomyPolicy,
    proposal: RescheduleProposal,
    *,
    incident_id: UUID,
    source_revision: int,
    attempt_keys: frozenset[str],
) -> tuple[tuple[AffectedReservation, str], ...]:
    """Envelope-filtered, budget-capped reschedule work for one assessment cycle.

    A successful reschedule moves commitments and therefore advances the
    recovery source revision, so the persisted proposal is single-shot: each
    cycle takes at most one new attempt and later cycles re-propose on fresh
    truth. Attempt keys already in the ledger replay idempotently (converging a
    retried cycle) without consuming fresh budget; only new attempts count
    against the per-incident cap.
    """

    replays: list[tuple[AffectedReservation, str]] = []
    new_attempt: tuple[AffectedReservation, str] | None = None
    for affected in proposal.affected:
        if not reschedule_within_envelope(policy, proposal, affected):
            continue
        key = autonomy_reschedule_key(
            incident_id=incident_id,
            reservation_id=affected.reservation_id,
            source_revision=source_revision,
        )
        if key in attempt_keys:
            replays.append((affected, key))
        elif new_attempt is None and len(attempt_keys) < policy.max_auto_actions_per_incident:
            new_attempt = (affected, key)
    if new_attempt is not None:
        replays.append(new_attempt)
    return tuple(replays)
