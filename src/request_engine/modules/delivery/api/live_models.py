from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.delivery.contracts.service_session import (
    InterruptionKind,
    ResourceActivity,
    ResourceActivityKind,
    ServiceSession,
    ServiceSessionInterruption,
    ServiceSessionOperationalSnapshot,
)


class StartServiceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resource_id: UUID
    location_id: UUID
    expected_queue_revision: int = Field(gt=0)
    actual_workload_classification_id: UUID | None = None


class PauseServiceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(gt=0)
    kind: InterruptionKind


class ResumeServiceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(gt=0)


class CompleteServiceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(gt=0)
    actual_workload_classification_id: UUID | None = None


class StartResourceActivityBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resource_id: UUID
    location_id: UUID | None = None
    kind: ResourceActivityKind


class EndResourceActivityBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(gt=0)


class ServiceSessionView(BaseModel):
    id: UUID
    queue_entry_id: UUID
    resource_id: UUID
    location_id: UUID
    status: str
    started_at: datetime
    completed_at: datetime | None
    actual_workload_classification_id: UUID | None
    revision: int

    @classmethod
    def from_contract(cls, item: ServiceSession) -> "ServiceSessionView":
        return cls(
            id=item.id,
            queue_entry_id=item.queue_entry_id,
            resource_id=item.resource_id,
            location_id=item.location_id,
            status=item.status.value,
            started_at=item.started_at,
            completed_at=item.completed_at,
            actual_workload_classification_id=item.actual_workload_classification_id,
            revision=item.revision,
        )


class ServiceSessionInterruptionView(BaseModel):
    id: UUID
    kind: str
    started_at: datetime
    ended_at: datetime | None

    @classmethod
    def from_contract(cls, item: ServiceSessionInterruption) -> "ServiceSessionInterruptionView":
        return cls(
            id=item.id,
            kind=item.kind.value,
            started_at=item.started_at,
            ended_at=item.ended_at,
        )


class ServiceSessionStatusView(ServiceSessionView):
    observed_at: datetime
    wall_clock_seconds: int
    interruption_seconds: int
    active_service_seconds: int
    interruptions: list[ServiceSessionInterruptionView]

    @classmethod
    def from_snapshot(cls, item: ServiceSessionOperationalSnapshot) -> "ServiceSessionStatusView":
        session = item.session
        return cls(
            **ServiceSessionView.from_contract(session).model_dump(),
            observed_at=item.observed_at,
            wall_clock_seconds=item.wall_clock_seconds,
            interruption_seconds=item.interruption_seconds,
            active_service_seconds=item.active_service_seconds,
            interruptions=[
                ServiceSessionInterruptionView.from_contract(interruption)
                for interruption in item.interruptions
            ],
        )


class ResourceActivityView(BaseModel):
    id: UUID
    resource_id: UUID
    location_id: UUID | None
    kind: str
    started_at: datetime
    ended_at: datetime | None
    revision: int

    @classmethod
    def from_contract(cls, item: ResourceActivity) -> "ResourceActivityView":
        return cls(
            id=item.id,
            resource_id=item.resource_id,
            location_id=item.location_id,
            kind=item.kind.value,
            started_at=item.started_at,
            ended_at=item.ended_at,
            revision=item.revision,
        )
