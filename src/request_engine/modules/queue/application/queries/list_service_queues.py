from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ServiceQueueSummary:
    id: UUID
    queue_key: str
    display_name: str
    location_id: UUID | None
    offering_id: UUID | None
    active: bool


class ServiceQueueCatalogReader(Protocol):
    async def list_service_queues(
        self,
        organization_id: UUID,
        *,
        active_only: bool = True,
    ) -> tuple[ServiceQueueSummary, ...]: ...


async def list_service_queues(
    reader: ServiceQueueCatalogReader,
    *,
    organization_id: UUID,
    active_only: bool = True,
) -> tuple[ServiceQueueSummary, ...]:
    return await reader.list_service_queues(organization_id, active_only=active_only)
