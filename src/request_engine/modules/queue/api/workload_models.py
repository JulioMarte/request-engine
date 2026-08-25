from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.queue.contracts.live_queue import WorkloadClassification


class CreateWorkloadClassificationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workload_key: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=200)


class UpdateWorkloadClassificationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(min_length=1, max_length=200)
    expected_revision: int = Field(gt=0)


class DeactivateWorkloadClassificationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(gt=0)


class WorkloadClassificationView(BaseModel):
    id: UUID
    workload_key: str
    display_name: str
    active: bool
    revision: int

    @classmethod
    def from_contract(cls, item: WorkloadClassification) -> "WorkloadClassificationView":
        return cls(
            id=item.id,
            workload_key=item.workload_key,
            display_name=item.display_name,
            active=item.active,
            revision=item.revision,
        )
