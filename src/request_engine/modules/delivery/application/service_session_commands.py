from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.modules.delivery.contracts.service_session import (
    InterruptionKind,
    ServiceSession,
)


@dataclass(frozen=True, slots=True)
class StartServiceCommand:
    organization_id: UUID
    principal_id: UUID
    queue_entry_id: UUID
    resource_id: UUID
    location_id: UUID
    expected_queue_revision: int
    idempotency_key: str
    actual_workload_classification_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class PauseServiceCommand:
    organization_id: UUID
    principal_id: UUID
    service_session_id: UUID
    expected_revision: int
    kind: InterruptionKind
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class ResumeServiceCommand:
    organization_id: UUID
    principal_id: UUID
    service_session_id: UUID
    expected_revision: int
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class CompleteServiceCommand:
    organization_id: UUID
    principal_id: UUID
    service_session_id: UUID
    expected_revision: int
    idempotency_key: str
    actual_workload_classification_id: UUID | None = None


class ServiceSessionExecutor(Protocol):
    async def start_service(self, command: StartServiceCommand) -> ServiceSession: ...
    async def pause_service(self, command: PauseServiceCommand) -> ServiceSession: ...
    async def resume_service(self, command: ResumeServiceCommand) -> ServiceSession: ...
    async def complete_service(self, command: CompleteServiceCommand) -> ServiceSession: ...
