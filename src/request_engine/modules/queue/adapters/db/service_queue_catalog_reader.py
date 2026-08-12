from typing import cast
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.queue.application.queries.list_service_queues import (
    ServiceQueueSummary,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction


class PostgresServiceQueueCatalogReader:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def list_service_queues(
        self,
        organization_id: UUID,
        *,
        active_only: bool = True,
    ) -> tuple[ServiceQueueSummary, ...]:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            rows = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT id, queue_key, display_name, location_id, offering_id, active
                            FROM request_engine.service_queues
                            WHERE organization_id = :organization_id
                              AND (:active_only = false OR active)
                            ORDER BY display_name, id
                            """
                        ),
                        {"organization_id": organization_id, "active_only": active_only},
                    )
                )
                .mappings()
                .all()
            )
        return tuple(
            ServiceQueueSummary(
                id=cast(UUID, row["id"]),
                queue_key=cast(str, row["queue_key"]),
                display_name=cast(str, row["display_name"]),
                location_id=cast(UUID | None, row["location_id"]),
                offering_id=cast(UUID | None, row["offering_id"]),
                active=cast(bool, row["active"]),
            )
            for row in rows
        )
