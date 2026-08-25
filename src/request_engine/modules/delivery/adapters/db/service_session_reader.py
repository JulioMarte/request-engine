from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.delivery.application.errors import ServiceSessionNotFound
from request_engine.modules.delivery.contracts.service_session import (
    ServiceSession,
    ServiceSessionStatus,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction


class PostgresServiceSessionReader:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def get(
        self,
        organization_id: UUID,
        service_session_id: UUID,
    ) -> ServiceSession:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            row = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT service_session_id AS id, queue_entry_id,
                                   resource_id, location_id,
                                   actual_workload_classification_id, status,
                                   started_at, completed_at, revision
                              FROM request_read.service_session_status_v1
                             WHERE organization_id = :organization_id
                               AND service_session_id = :service_session_id
                            """
                        ),
                        {
                            "organization_id": organization_id,
                            "service_session_id": service_session_id,
                        },
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            raise ServiceSessionNotFound(service_session_id)
        return ServiceSession(
            id=cast(UUID, row["id"]),
            queue_entry_id=cast(UUID, row["queue_entry_id"]),
            resource_id=cast(UUID, row["resource_id"]),
            location_id=cast(UUID, row["location_id"]),
            status=ServiceSessionStatus(cast(str, row["status"])),
            started_at=cast(datetime, row["started_at"]),
            completed_at=cast(datetime | None, row["completed_at"]),
            actual_workload_classification_id=cast(
                UUID | None,
                row["actual_workload_classification_id"],
            ),
            revision=cast(int, row["revision"]),
        )
