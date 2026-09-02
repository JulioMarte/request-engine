from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.queue.api.models import QueueEntryView
from request_engine.modules.queue.contracts.same_day_selection import (
    OperatorSelectReason,
    RecallHold,
    RecallHoldKind,
    RecallHoldReason,
    SkipReason,
    SkipResult,
)


class OperatorSelectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    reason: OperatorSelectReason


class RecallHoldBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    kind: RecallHoldKind
    release_at: datetime | None = None
    reason: RecallHoldReason | None = None


class ReleaseRecallHoldBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hold_id: UUID
    expected_revision: int = Field(ge=1)


class SkipQueueHeadBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: SkipReason


class RecallHoldView(BaseModel):
    id: UUID
    queue_id: UUID
    queue_entry_id: UUID
    queue_entry_revision: int
    kind: RecallHoldKind
    release_at: datetime | None
    reason: RecallHoldReason | None
    created_at: datetime
    released_at: datetime | None

    @classmethod
    def from_contract(cls, item: RecallHold) -> "RecallHoldView":
        return cls(
            id=item.id,
            queue_id=item.queue_id,
            queue_entry_id=item.queue_entry_id,
            queue_entry_revision=item.queue_entry_revision,
            kind=item.kind,
            release_at=item.release_at,
            reason=item.reason,
            created_at=item.created_at,
            released_at=item.released_at,
        )


class SkipQueueHeadView(BaseModel):
    skipped_entry_id: UUID
    called_entry: QueueEntryView | None

    @classmethod
    def from_contract(cls, item: SkipResult) -> "SkipQueueHeadView":
        return cls(
            skipped_entry_id=item.skipped_entry_id,
            called_entry=(
                QueueEntryView.from_contract(item.called_entry)
                if item.called_entry is not None
                else None
            ),
        )
