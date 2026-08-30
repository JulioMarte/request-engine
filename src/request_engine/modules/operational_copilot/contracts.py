from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CopilotContext:
    organization_id: UUID
    principal_id: UUID
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class CreateRecoveryProposalIntent:
    service_queue_id: UUID
    search_days: int = 7


@dataclass(frozen=True, slots=True)
class ExecuteRecoveryIntent:
    proposal_id: UUID
    reservation_id: UUID
    expected_source_fingerprint: str
    expected_proposal_fingerprint: str
    allow_subject_override: bool = False
    notify: bool = True


CopilotIntent = CreateRecoveryProposalIntent | ExecuteRecoveryIntent


@dataclass(frozen=True, slots=True)
class ValidatedCopilotIntent:
    value: CopilotIntent
