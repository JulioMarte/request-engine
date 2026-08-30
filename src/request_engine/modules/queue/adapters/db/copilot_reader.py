from typing import cast
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.queue.contracts.copilot import (
    CopilotQueueMatch,
    CopilotQueueReader,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction


class PostgresCopilotQueueReader(CopilotQueueReader):
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def list_queues(
        self,
        *,
        organization_id: UUID,
    ) -> tuple[CopilotQueueMatch, ...]:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT id, location_id
                        FROM request_engine.service_queues
                        WHERE organization_id=:organization_id
                        ORDER BY id
                        """
                    ),
                    {"organization_id": organization_id},
                )
            ).mappings()
            return tuple(
                CopilotQueueMatch(
                    service_queue_id=cast(UUID, row["id"]),
                    location_id=cast(UUID, row["location_id"]),
                )
                for row in rows
            )
