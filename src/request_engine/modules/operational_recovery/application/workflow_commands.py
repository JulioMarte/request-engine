from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class SetRecoveryIntakeCommand:
    organization_id: UUID
    principal_id: UUID
    incident_id: UUID
    expected_source_revision: int
    expected_intake_revision: int
    accepting: bool
    idempotency_key: str
    reason: str | None = None
    effective_until: datetime | None = None


@dataclass(frozen=True, slots=True)
class ExtendRecoveryDayCommand:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    incident_id: UUID
    expected_source_revision: int
    assignment_id: UUID
    start_at: datetime
    end_at: datetime
    expected_location_operational_revision: int
    expected_resource_availability_revision: int
    idempotency_key: str
    reason: str


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
