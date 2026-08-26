from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.modules.delivery.contracts.service_session import (
    ResourceActivity,
    ResourceActivityKind,
)


@dataclass(frozen=True, slots=True)
class StartResourceActivityCommand:
    organization_id: UUID
    principal_id: UUID
    resource_id: UUID
    kind: ResourceActivityKind
    idempotency_key: str
    location_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class EndResourceActivityCommand:
    organization_id: UUID
    principal_id: UUID
    resource_activity_id: UUID
    expected_revision: int
    idempotency_key: str


class ResourceActivityExecutor(Protocol):
    async def start_resource_activity(
        self, command: StartResourceActivityCommand
    ) -> ResourceActivity: ...

    async def end_resource_activity(
        self, command: EndResourceActivityCommand
    ) -> ResourceActivity: ...
