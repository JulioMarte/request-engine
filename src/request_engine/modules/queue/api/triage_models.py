from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.queue.contracts.triage import (
    OperatorSelectReason,
    QueueTriageResult,
    RecallHoldKind,
    SkipReason,
)


class OperatorSelectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: OperatorSelectReason
    expected_revision: int = Field(gt=0)


class RecallHoldBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    condition_kind: RecallHoldKind
    expected_revision: int = Field(gt=0)
    until_at: datetime | None = None
    event_key: str | None = Field(default=None, max_length=64)
    reason: str | None = Field(default=None, min_length=1, max_length=250)


class SkipBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: SkipReason
    expected_revision: int = Field(gt=0)


class ReleaseRecallHoldBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hold_id: UUID
    expected_revision: int = Field(gt=0)


class RecallHoldView(BaseModel):
    id: UUID
    queue_entry_id: UUID
    condition_kind: str
    until_at: datetime | None
    event_key: str | None
    reason: str | None
    created_at: datetime


class QueueTriageResultView(BaseModel):
    queue_entry_id: UUID
    queue_id: UUID
    status: str
    revision: int
    action: str
    reason: str | None
    hold: RecallHoldView | None = None

    @classmethod
    def from_contract(cls, result: QueueTriageResult) -> "QueueTriageResultView":
        hold = result.hold
        return cls(
            queue_entry_id=result.queue_entry_id,
            queue_id=result.queue_id,
            status=result.status,
            revision=result.revision,
            action=result.action,
            reason=result.reason,
            hold=(
                None
                if hold is None
                else RecallHoldView(
                    id=hold.id,
                    queue_entry_id=hold.queue_entry_id,
                    condition_kind=hold.condition_kind.value,
                    until_at=hold.until_at,
                    event_key=hold.event_key,
                    reason=hold.reason,
                    created_at=hold.created_at,
                )
            ),
        )
