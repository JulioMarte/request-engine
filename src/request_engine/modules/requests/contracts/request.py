from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class RequestStatus(StrEnum):
    OPEN = "open"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class RequestParticipantInput:
    party_id: UUID
    role_key: str


@dataclass(frozen=True, slots=True)
class ExternalCorrelationInput:
    correlation_kind: str
    provider_key: str
    external_key: str


@dataclass(frozen=True, slots=True)
class RequestParticipant:
    party_id: UUID
    role_key: str


@dataclass(frozen=True, slots=True)
class ExternalCorrelation:
    id: UUID
    correlation_kind: str
    provider_key: str
    external_key: str


@dataclass(frozen=True, slots=True)
class Request:
    id: UUID
    request_definition_version_id: UUID
    requester_party_id: UUID | None
    recipient_party_id: UUID | None
    status: RequestStatus
    payload: dict[str, object]
    result_payload: dict[str, object] | None
    revision: int
    created_at: datetime
    completed_at: datetime | None
    updated_at: datetime
    participants: tuple[RequestParticipant, ...] = ()
    correlations: tuple[ExternalCorrelation, ...] = ()
