from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.queue.contracts.live_queue import (
    LiveQueueEntry,
    StaffQueueEntry,
    WorkloadClassification,
)


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
            expected_workload_classification_id=(item.expected_workload_classification_id),
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
    queue_revision: int
    service_revision: int | None

    @classmethod
    def from_contract(cls, item: StaffQueueEntry) -> "StaffQueueEntryView":
        return cls(
            queue_entry_id=item.queue_entry_id,
            queue_id=item.queue_id,
            subject_party_id=item.subject_party_id,
            subject_display_name=item.subject_display_name,
            reservation_id=item.reservation_id,
            status=item.status,
            scheduled_at=item.scheduled_at,
            arrived_at=item.arrived_at,
            admitted_at=item.admitted_at,
            called_at=item.called_at,
            expected_workload_key=item.expected_workload_key,
            service_session_id=item.service_session_id,
            service_status=item.service_status,
            actual_resource_id=item.actual_resource_id,
            actual_location_id=item.actual_location_id,
            actual_workload_key=item.actual_workload_key,
            service_started_at=item.service_started_at,
            service_completed_at=item.service_completed_at,
            queue_revision=item.queue_revision,
            service_revision=item.service_revision,
        )


class WorkloadClassificationView(BaseModel):
    id: UUID
    workload_key: str
    display_name: str

    @classmethod
    def from_contract(
        cls,
        item: WorkloadClassification,
    ) -> "WorkloadClassificationView":
        return cls(
            id=item.id,
            workload_key=item.workload_key,
            display_name=item.display_name,
        )
