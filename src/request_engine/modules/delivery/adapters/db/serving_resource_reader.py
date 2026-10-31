from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.delivery.contracts.serving_resources import (
    LocationServingResources,
    ServingResource,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction

# Same predicates as lock_resource + require_execution_assignment in start_service.
_SERVING_SQL = """
SELECT r.id AS resource_id, r.display_name
  FROM request_engine.resources r
 WHERE r.organization_id = :organization_id
   AND r.active
   AND EXISTS (
        SELECT 1
          FROM request_engine.resource_location_assignments a
         WHERE a.organization_id = r.organization_id
           AND a.resource_id = r.id
           AND a.location_id = :location_id
           AND a.status = 'active'
           AND a.effective_during @> CAST(:at AS timestamptz)
       )
 ORDER BY lower(r.display_name), r.id
"""


class PostgresServingResourceReader:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def read_serving_resources(
        self, organization_id: UUID, location_id: UUID
    ) -> LocationServingResources | None:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            located = (
                await session.execute(
                    text(
                        "SELECT clock_timestamp() AS at, EXISTS ("
                        "SELECT 1 FROM request_engine.locations "
                        "WHERE organization_id = :organization_id AND id = :location_id"
                        ") AS visible"
                    ),
                    {"organization_id": organization_id, "location_id": location_id},
                )
            ).one()
            if not located.visible:
                return None
            at = cast(datetime, located.at)
            rows = (
                await session.execute(
                    text(_SERVING_SQL),
                    {"organization_id": organization_id, "location_id": location_id, "at": at},
                )
            ).all()
        return LocationServingResources(
            location_id=location_id,
            observed_at=at,
            resources=tuple(
                ServingResource(
                    resource_id=cast(UUID, row.resource_id), display_name=row.display_name
                )
                for row in rows
            ),
        )
