from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CopilotQueueMatch:
    service_queue_id: UUID
    location_id: UUID


class CopilotQueueReader(Protocol):
    async def list_queues(
        self,
        *,
        organization_id: UUID,
    ) -> tuple[CopilotQueueMatch, ...]: ...
