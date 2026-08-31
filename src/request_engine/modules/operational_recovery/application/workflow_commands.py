from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from request_engine.modules.operational_recovery.contracts.workflow import (
    RecoveryExternalTarget,
)
from request_engine.modules.operational_recovery.contracts.workflow_commands import (
    ExtendRecoveryDayCommand,
    SetRecoveryIntakeCommand,
)

__all__ = [
    "CommunicateImpactRecoveryActionCommand",
    "ExtendRecoveryDayCommand",
    "ReplaceResourceRecoveryActionCommand",
    "RescheduleRecoveryActionCommand",
    "SetRecoveryIntakeCommand",
]


@dataclass(frozen=True, slots=True)
class RescheduleRecoveryActionCommand:
    organization_id: UUID
    principal_id: UUID
    incident_id: UUID
    expected_source_revision: int
    proposal_id: UUID
    reservation_id: UUID
    expected_source_fingerprint: str
    expected_proposal_fingerprint: str
    idempotency_key: str
    allow_subject_override: bool


@dataclass(frozen=True, slots=True)
class CommunicateImpactRecoveryActionCommand:
    organization_id: UUID
    principal_id: UUID
    incident_id: UUID
    expected_source_revision: int
    recipient_party_id: UUID
    idempotency_key: str
    message: str | None = None
    not_before: datetime | None = None


@dataclass(frozen=True, slots=True)
class ReplaceResourceRecoveryActionCommand:
    organization_id: UUID
    principal_id: UUID
    incident_id: UUID
    expected_source_revision: int
    proposal_id: UUID
    reservation_id: UUID
    expected_source_fingerprint: str
    expected_proposal_fingerprint: str
    idempotency_key: str
    allow_subject_override: bool
    external_target: RecoveryExternalTarget | None = None
