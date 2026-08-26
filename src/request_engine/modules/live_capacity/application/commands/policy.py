from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CreateProjectionScopeCommand:
    organization_id: UUID
    principal_id: UUID
    service_queue_id: UUID
    resource_id: UUID
    location_id: UUID
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class UpdateProjectionScopeCommand:
    organization_id: UUID
    principal_id: UUID
    policy_id: UUID
    resource_id: UUID
    location_id: UUID
    active: bool
    expected_revision: int
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class CreateWorkloadEstimatePolicyCommand:
    organization_id: UUID
    principal_id: UUID
    workload_classification_id: UUID
    duration_seconds: int
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class UpdateWorkloadEstimatePolicyCommand:
    organization_id: UUID
    principal_id: UUID
    policy_id: UUID
    duration_seconds: int
    active: bool
    expected_revision: int
    idempotency_key: str
