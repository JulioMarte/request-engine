from typing import Protocol
from uuid import UUID

from request_engine.modules.queue.contracts.service_queue import QueueStatus


class QueueStatusReader(Protocol):
    async def get_queue_status(
        self,
        organization_id: UUID,
        principal_id: UUID,
        queue_id: UUID,
        subject_party_id: UUID,
        allow_subject_override: bool,
    ) -> QueueStatus: ...


async def get_queue_status(
    reader: QueueStatusReader,
    *,
    organization_id: UUID,
    principal_id: UUID,
    queue_id: UUID,
    subject_party_id: UUID,
    allow_subject_override: bool = False,
) -> QueueStatus:
    """Return current FIFO state only after subject authority is established."""

    return await reader.get_queue_status(
        organization_id,
        principal_id,
        queue_id,
        subject_party_id,
        allow_subject_override,
    )
