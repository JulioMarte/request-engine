from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class CommunicationTaskStatus(StrEnum):
    PENDING = "pending"
    DELIVERING = "delivering"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class CommunicationTask:
    id: UUID
    recipient_party_id: UUID
    contact_point_id: UUID | None
    purpose: str
    source_kind: str | None
    source_id: UUID | None
    channel_policy: dict[str, object]
    template_key: str
    template_version: int
    render_context: dict[str, object]
    dedupe_key: str | None
    not_before: datetime | None
    expires_at: datetime | None
    status: CommunicationTaskStatus
    revision: int
