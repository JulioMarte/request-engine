from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.queue.contracts.live_queue import LiveQueueEntry, StaffQueueEntry


class CheckInBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject_party_id: UUID
    reservation_id: UUID | None = None
    offering_id: UUID | None = None
    expected_workload_classification_id: UUID | None = None


class ClassifyExpectedWorkloadBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(gt=0)
    expected_workload_classification_id: UUID | None


class MarkNoShowBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(gt=0)


class LiveQueueEntryView(BaseModel):
    id: UUID
    queue_id: UUID
    subject_party_id: UUID
    reservation_id: UUID | None
    offering_id: UUID | None
    status: str
    arrived_at: datetime
    admitted_at: datetime
    called_at: datetime | None
    expected_workload_classification_id: UUID | None
    revision: int

    @classmethod
    def from_contract(cls, item: LiveQueueEntry) -> "LiveQueueEntryView":
        return cls(
            id=item.id,
            queue_id=item.queue_id,
            subject_party_id=item.subject_party_id,
            reservation_id=item.reservation_id,
            offering_id=item.offering_id,
            status=item.status,
            arrived_at=item.arrived_at,
            admitted_at=item.admitted_at,
            called_at=item.called_at,
            expected_workload_classification_id=item.expected_workload_classification_id,
            revision=item.revision,
        )


class StaffQueueEntryView(BaseModel):
    queue_entry_id: UUID
    queue_id: UUID
    subject_party_id: UUID
    subject_display_name: str
    reservation_id: UUID | None
    status: str
    scheduled_at: datetime | None
    arrived_at: datetime
    admitted_at: datetime
    called_at: datetime | None
    expected_workload_key: str | None
    service_session_id: UUID | None
    service_status: str | None
    actual_resource_id: UUID | None
    actual_location_id: UUID | None
    actual_workload_key: str | None
    service_started_at: datetime | None
    service_completed_at: datetime | None
    recall_eligible: bool
    recall_hold_id: UUID | None
    recall_hold_kind: str | None
    recall_hold_until_at: datetime | None
    recall_hold_event_key: str | None
    recall_hold_reason: str | None
    active_skip_reason: str | None
    queue_revision: int
    service_revision: int | None

    @classmethod
    def from_contract(cls, item: StaffQueueEntry) -> "StaffQueueEntryView":
        return cls(**{name: getattr(item, name) for name in cls.model_fields})
