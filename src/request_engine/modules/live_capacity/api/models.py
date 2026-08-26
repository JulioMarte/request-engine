from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.live_capacity.contracts.policy import (
    ProjectionScopePolicy,
    WorkloadEstimatePolicy,
)


class CreateProjectionScopeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    service_queue_id: UUID
    resource_id: UUID
    location_id: UUID


class UpdateProjectionScopeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resource_id: UUID
    location_id: UUID
    active: bool
    expected_revision: int = Field(gt=0)


class CreateWorkloadEstimatePolicyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workload_classification_id: UUID
    duration_seconds: int = Field(gt=0)


class UpdateWorkloadEstimatePolicyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    duration_seconds: int = Field(gt=0)
    active: bool
    expected_revision: int = Field(gt=0)


class ProjectionScopePolicyView(BaseModel):
    id: UUID
    service_queue_id: UUID
    resource_id: UUID
    location_id: UUID
    active: bool
    revision: int

    @classmethod
    def from_contract(cls, item: ProjectionScopePolicy) -> "ProjectionScopePolicyView":
        return cls(
            id=item.id,
            service_queue_id=item.service_queue_id,
            resource_id=item.resource_id,
            location_id=item.location_id,
            active=item.active,
            revision=item.revision,
        )


class WorkloadEstimatePolicyView(BaseModel):
    id: UUID
    workload_classification_id: UUID
    duration_seconds: int
    active: bool
    revision: int

    @classmethod
    def from_contract(cls, item: WorkloadEstimatePolicy) -> "WorkloadEstimatePolicyView":
        return cls(
            id=item.id,
            workload_classification_id=item.workload_classification_id,
            duration_seconds=item.duration_seconds,
            active=item.active,
            revision=item.revision,
        )
