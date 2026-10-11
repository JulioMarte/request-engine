from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.requests.adapters.db.definition_management import (
    DEFINITION_STATE_SELECT,
    read_definition_state,
    state_from_row,
)
from request_engine.modules.requests.application.commands.manage_definition import (
    RequestDefinitionState,
)
from request_engine.modules.requests.application.queries.admin_reads import RequestInboxItem
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.db.tenant_principal_authority_reader import (
    require_current_tenant_capability,
)


class PostgresRequestAdministrationReader:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def list_definitions(
        self,
        organization_id: UUID,
        *,
        principal_id: UUID,
        limit: int,
        after_id: UUID | None,
    ) -> tuple[RequestDefinitionState, ...]:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            await require_current_tenant_capability(
                session,
                organization_id=organization_id,
                principal_id=principal_id,
                capability="requests.read_definitions",
            )
            rows = (
                (
                    await session.execute(
                        text(
                            DEFINITION_STATE_SELECT
                            + """
                WHERE d.organization_id=:org
                AND (CAST(:after_id AS uuid) IS NULL OR d.id > CAST(:after_id AS uuid))
                ORDER BY d.id LIMIT :limit
            """
                        ),
                        {
                            "org": organization_id,
                            "after_id": after_id,
                            "limit": limit,
                            "version": None,
                        },
                    )
                )
                .mappings()
                .all()
            )
        return tuple(state_from_row(row) for row in rows)

    async def get_definition(
        self,
        organization_id: UUID,
        definition_id: UUID,
        version: int | None,
        *,
        principal_id: UUID,
    ) -> RequestDefinitionState | None:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            await require_current_tenant_capability(
                session,
                organization_id=organization_id,
                principal_id=principal_id,
                capability="requests.read_definitions",
            )
            return await read_definition_state(session, organization_id, definition_id, version)

    async def list_inbox(
        self,
        organization_id: UUID,
        *,
        principal_id: UUID,
        limit: int,
        status: str | None,
        after_created_at: datetime | None,
        after_id: UUID | None,
    ) -> tuple[RequestInboxItem, ...]:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            await require_current_tenant_capability(
                session,
                organization_id=organization_id,
                principal_id=principal_id,
                capability="requests.read_inbox",
            )
            rows = (
                (
                    await session.execute(
                        text("""
                SELECT r.id,r.request_definition_version_id,d.id AS definition_id,
                       d.request_key,v.version AS definition_version,
                       r.requester_party_id,r.recipient_party_id,r.status,r.revision,r.created_at
                FROM request_engine.requests r
                JOIN request_engine.request_definition_versions v
                  ON v.organization_id=r.organization_id AND v.id=r.request_definition_version_id
                JOIN request_engine.request_definitions d
                  ON d.organization_id=v.organization_id AND d.id=v.request_definition_id
                WHERE r.organization_id=:org AND (CAST(:status AS text) IS NULL OR r.status=:status)
                  AND (CAST(:after_id AS uuid) IS NULL OR (r.created_at,r.id) <
                       (CAST(:after_at AS timestamptz),CAST(:after_id AS uuid)))
                ORDER BY r.created_at DESC,r.id DESC LIMIT :limit
            """),
                        {
                            "org": organization_id,
                            "status": status,
                            "after_at": after_created_at,
                            "after_id": after_id,
                            "limit": limit,
                        },
                    )
                )
                .mappings()
                .all()
            )
        return tuple(
            RequestInboxItem(
                cast(UUID, row["id"]),
                cast(UUID, row["request_definition_version_id"]),
                cast(UUID, row["definition_id"]),
                cast(str, row["request_key"]),
                cast(int, row["definition_version"]),
                cast(UUID | None, row["requester_party_id"]),
                cast(UUID | None, row["recipient_party_id"]),
                cast(str, row["status"]),
                cast(int, row["revision"]),
                cast(datetime, row["created_at"]),
            )
            for row in rows
        )
