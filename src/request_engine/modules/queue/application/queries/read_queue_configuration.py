from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ServiceQueueConfiguration:
    queue_id: UUID
    queue_key: str
    display_name: str
    location_id: UUID | None
    offering_id: UUID | None
    policy_key: str
    active: bool
    revision: int


class ServiceQueueConfigurationReader(Protocol):
    async def read_queue_configuration(
        self,
        organization_id: UUID,
        *,
        principal_id: UUID,
        authority_party_id: UUID,
        queue_id: UUID | None = None,
        after_id: UUID | None = None,
        limit: int = 50,
    ) -> tuple[ServiceQueueConfiguration, ...]: ...
