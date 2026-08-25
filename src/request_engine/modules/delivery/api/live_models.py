from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.delivery.contracts.service_session import (
    InterruptionKind,
    ResourceActivity,
    ResourceActivityKind,
    ServiceSession,
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
