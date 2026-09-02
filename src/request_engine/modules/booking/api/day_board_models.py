from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from request_engine.modules.booking.contracts.day_board import DayBoardEntry


class DayBoardEntryView(BaseModel):
    reservation_id: UUID
    subject_party_id: UUID
    subject_display_name: str
    offering_version_id: UUID
    location_id: UUID | None
    start_at: datetime
    end_at: datetime
    reservation_status: str
    reservation_revision: int
    attendance_status: str
    attendance_responded_at: datetime | None
    attendance_outcome_status: str
    checked_in_at: datetime | None
    no_show_at: datetime | None
    reported_arrival_estimate_at: datetime | None
    effective_arrival_estimate_at: datetime | None
    arrival_estimate_source_kind: str | None

    @classmethod
    def from_contract(cls, entry: DayBoardEntry) -> "DayBoardEntryView":
        return cls(**{field: getattr(entry, field) for field in cls.model_fields})
