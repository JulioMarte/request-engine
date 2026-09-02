from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class OperatorSelectReason(StrEnum):
    URGENT = "urgent"
    SCHEDULED_COMMITMENT = "scheduled_commitment"
    OPERATOR_OVERRIDE = "operator_override"


class RecallHoldKind(StrEnum):
    UNTIL_TIME = "until_time"
    UNTIL_EVENT = "until_event"
    UNTIL_CUSTOMER_INITIATES = "until_customer_initiates"


class SkipReason(StrEnum):
    TEMPORARILY_UNAVAILABLE = "temporarily_unavailable"
    NO_RESPONSE = "no_response"
    OPERATOR_OVERRIDE = "operator_override"


@dataclass(frozen=True, slots=True)
class RecallHold:
    id: UUID
    queue_entry_id: UUID
    condition_kind: RecallHoldKind
    until_at: datetime | None
    event_key: str | None
    reason: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class QueueTriageResult:
    queue_entry_id: UUID
    queue_id: UUID
    status: str
    revision: int
    action: str
    reason: str | None
    hold: RecallHold | None = None
