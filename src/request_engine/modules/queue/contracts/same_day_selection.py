from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from request_engine.modules.queue.contracts.service_queue import QueueEntry


class OperatorSelectReason(StrEnum):
    URGENT_OPERATIONAL_NEED = "urgent_operational_need"
    BOOKED_TIME_DUE = "booked_time_due"
    OPERATOR_OVERRIDE = "operator_override"


class RecallHoldKind(StrEnum):
    UNTIL_TIME = "until_time"
    UNTIL_CUSTOMER_INITIATES = "until_customer_initiates"


class RecallHoldReason(StrEnum):
    STEPPED_AWAY = "stepped_away"
    TEMPORARILY_UNAVAILABLE = "temporarily_unavailable"
    OPERATOR_OVERRIDE = "operator_override"


class SkipReason(StrEnum):
    TEMPORARILY_UNAVAILABLE = "temporarily_unavailable"
    NO_RESPONSE = "no_response"
    OPERATOR_OVERRIDE = "operator_override"


@dataclass(frozen=True, slots=True)
class RecallHold:
    id: UUID
    queue_id: UUID
    queue_entry_id: UUID
    queue_entry_revision: int
    kind: RecallHoldKind
    release_at: datetime | None
    reason: RecallHoldReason | None
    created_at: datetime
    released_at: datetime | None


@dataclass(frozen=True, slots=True)
class SkipResult:
    skipped_entry_id: UUID
    called_entry: QueueEntry | None
