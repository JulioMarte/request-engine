from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class CapacityHoldStatus(StrEnum):
    ACTIVE = "active"
    CONSUMED = "consumed"
    RELEASED = "released"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class CapacityHold:
    id: UUID
    offering_version_id: UUID
    subject_party_id: UUID
    location_id: UUID | None
    start_at: datetime
    end_at: datetime
    expires_at: datetime
    status: CapacityHoldStatus
    revision: int
