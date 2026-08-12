from typing import Protocol
from uuid import UUID

from request_engine.modules.queue.contracts.service_queue import QueueStatus


class QueueStatusReader(Protocol):
    async def get_queue_status(
        self,
        organization_id: UUID,
        queue_id: UUID,
        subject_party_id: UUID,
    ) -> QueueStatus: ...


async def get_queue_status(
    reader: QueueStatusReader,
    *,
    organization_id: UUID,
    queue_id: UUID,
    subject_party_id: UUID,
) -> QueueStatus:
    """Return the caller-safe current FIFO queue state for one subject."""

    return await reader.get_queue_status(organization_id, queue_id, subject_party_id)
