from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CreateRecoveryProposalCommand:
    organization_id: UUID
    principal_id: UUID
    service_queue_id: UUID
    idempotency_key: str
    search_days: int = 7


@dataclass(frozen=True, slots=True)
class ExecuteRecoveryCommand:
    organization_id: UUID
    principal_id: UUID
    proposal_id: UUID
    reservation_id: UUID
    expected_source_fingerprint: str
    expected_proposal_fingerprint: str
    idempotency_key: str
    allow_subject_override: bool
    notify: bool = True
