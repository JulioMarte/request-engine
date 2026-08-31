from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CopilotContext:
    organization_id: UUID
    principal_id: UUID
    idempotency_key: str
    authority_party_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class CreateRecoveryProposalIntent:
    service_queue_id: UUID
    search_days: int = 7


@dataclass(frozen=True, slots=True)
class ExecuteRecoveryIntent:
    proposal_id: UUID
    reservation_id: UUID
    expected_source_fingerprint: str | None = None
    expected_proposal_fingerprint: str | None = None
    allow_subject_override: bool = False
    notify: bool = True


@dataclass(frozen=True, slots=True)
class SetRecoveryIntakeIntent:
    incident_id: UUID
    accepting: bool
    expected_source_revision: int
    expected_intake_revision: int
    reason: str | None = None
    effective_until: datetime | None = None


@dataclass(frozen=True, slots=True)
class ExtendRecoveryDayIntent:
    incident_id: UUID
    assignment_id: UUID
    start_at: datetime
    end_at: datetime
    expected_source_revision: int
    expected_location_operational_revision: int
    expected_resource_availability_revision: int
    reason: str


@dataclass(frozen=True, slots=True)
class SetOperationalIntakeIntent:
    service_queue_id: UUID
    accepting: bool
    expected_intake_revision: int
    reason: str | None = None
    effective_until: datetime | None = None


@dataclass(frozen=True, slots=True)
class ExtendOperationalDayIntent:
    assignment_id: UUID
    start_at: datetime
    end_at: datetime
    expected_resource_availability_revision: int
    reason: str


@dataclass(frozen=True, slots=True)
class PublishDiscoverySupplyIntent:
    offering_id: UUID
    location_id: UUID
    effective_start: datetime
    effective_end: datetime | None = None
    resource_id: UUID | None = None
    provider_visibility: str = "hidden"
    effective_start_is_resolved_now: bool = False


@dataclass(frozen=True, slots=True)
class RevokeDiscoveryPublicationIntent:
    publication_id: UUID
    expected_revision: int


@dataclass(frozen=True, slots=True)
class ShowAtRiskReservationsIntent:
    service_queue_id: UUID


CopilotIntent = (
    CreateRecoveryProposalIntent
    | ExecuteRecoveryIntent
    | SetRecoveryIntakeIntent
    | ExtendRecoveryDayIntent
    | SetOperationalIntakeIntent
    | ExtendOperationalDayIntent
    | PublishDiscoverySupplyIntent
    | RevokeDiscoveryPublicationIntent
    | ShowAtRiskReservationsIntent
)


@dataclass(frozen=True, slots=True)
class AtRiskReservationsQuery:
    organization_id: UUID
    service_queue_id: UUID


@dataclass(frozen=True, slots=True)
class ValidatedCopilotIntent:
    value: CopilotIntent


@dataclass(frozen=True, slots=True)
class CopilotExecutionReceipt:
    owner: str
    action: str
    result_id: UUID
    status: str
    idempotency_key: str
