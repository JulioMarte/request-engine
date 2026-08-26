from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.delivery.contracts.service_session import (
    ResourceActivity,
    ResourceActivityKind,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction


class PostgresResourceActivityReader:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def list_for_resource(
        self,
        organization_id: UUID,
        resource_id: UUID,
        *,
        active_only: bool,
    ) -> tuple[ResourceActivity, ...]:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            rows = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT id, resource_id, location_id, activity_kind,
                                   started_at, ended_at, revision
                              FROM request_engine.resource_activities
                             WHERE organization_id = :organization_id
                               AND resource_id = :resource_id
                               AND (:active_only = false OR ended_at IS NULL)
                             ORDER BY started_at DESC, id DESC
                            """
                        ),
                        {
                            "organization_id": organization_id,
                            "resource_id": resource_id,
                            "active_only": active_only,
                        },
                    )
                )
                .mappings()
                .all()
            )
        return tuple(
            ResourceActivity(
                id=cast(UUID, row["id"]),
                resource_id=cast(UUID, row["resource_id"]),
                location_id=cast(UUID | None, row["location_id"]),
                kind=ResourceActivityKind(cast(str, row["activity_kind"])),
                started_at=cast(datetime, row["started_at"]),
                ended_at=cast(datetime | None, row["ended_at"]),
                revision=cast(int, row["revision"]),
            )
            for row in rows
        )
