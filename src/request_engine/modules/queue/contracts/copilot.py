from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CopilotQueueMatch:
    service_queue_id: UUID
    location_id: UUID
    offering_id: UUID | None = None
    display_name: str | None = None


class CopilotQueueReader(Protocol):
    async def list_queues(
        self,
        *,
        organization_id: UUID,
    ) -> tuple[CopilotQueueMatch, ...]: ...
