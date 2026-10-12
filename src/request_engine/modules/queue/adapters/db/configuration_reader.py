from typing import cast
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.queue.application.queries.read_queue_configuration import (
    ServiceQueueConfiguration,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.db.tenant_principal_authority_reader import (
    require_current_tenant_capability,
)
from request_engine.platform.security.operational_authority import (
    MANAGE_CONTEXTUAL_SUPPLY_SCOPE,
    require_principal_serialized_operational_authority,
)


class PostgresServiceQueueConfigurationReader:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def read_queue_configuration(
        self,
        organization_id: UUID,
        *,
        principal_id: UUID,
        authority_party_id: UUID,
        queue_id: UUID | None = None,
        after_id: UUID | None = None,
        limit: int = 50,
    ) -> tuple[ServiceQueueConfiguration, ...]:
        if not 1 <= limit <= 101:
            raise ValueError("configuration read limit must be between 1 and 101")
        async with tenant_transaction(self._session_factory, organization_id) as session:
            await require_current_tenant_capability(
                session,
                organization_id=organization_id,
                principal_id=principal_id,
                capability="queue.read_configuration",
            )
            await require_principal_serialized_operational_authority(
                session,
                organization_id=organization_id,
                principal_id=principal_id,
                authority_party_id=authority_party_id,
                scope_key=MANAGE_CONTEXTUAL_SUPPLY_SCOPE,
            )
            rows = (
                (
                    await session.execute(
                        text("""
                            SELECT id, queue_key, display_name, location_id, offering_id,
                                   policy_key, active, revision
                            FROM request_engine.service_queues
                            WHERE organization_id=:organization_id
                              AND (CAST(:queue_id AS uuid) IS NULL OR id=CAST(:queue_id AS uuid))
                              AND (CAST(:after_id AS uuid) IS NULL OR id>CAST(:after_id AS uuid))
                            ORDER BY id LIMIT :limit
                        """),
                        {
                            "organization_id": organization_id,
                            "queue_id": queue_id,
                            "after_id": after_id,
                            "limit": limit,
                        },
                    )
                )
                .mappings()
                .all()
            )
        return tuple(
            ServiceQueueConfiguration(
                queue_id=cast(UUID, row["id"]),
                queue_key=cast(str, row["queue_key"]),
                display_name=cast(str, row["display_name"]),
                location_id=cast(UUID | None, row["location_id"]),
                offering_id=cast(UUID | None, row["offering_id"]),
                policy_key=cast(str, row["policy_key"]),
                active=cast(bool, row["active"]),
                revision=cast(int, row["revision"]),
            )
            for row in rows
        )
