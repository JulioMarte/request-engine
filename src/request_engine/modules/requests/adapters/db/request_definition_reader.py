from typing import cast
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.requests.application.errors import RequestDefinitionNotFound
from request_engine.modules.requests.contracts.definitions import (
    ResolvedRequestDefinitionVersion,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction


class PostgresRequestDefinitionResolver:
    """Resolve an active tenant RequestDefinition to one exact immutable version."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def resolve_request_definition(
        self,
        *,
        organization_id: UUID,
        request_key: str,
        version: int | None,
    ) -> ResolvedRequestDefinitionVersion:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            if version is None:
                statement = text(
                    """
                    SELECT rdv.id,
                           rd.request_key,
                           rdv.version
                    FROM request_engine.request_definitions AS rd
                    JOIN request_engine.request_definition_versions AS rdv
                      ON rdv.organization_id = rd.organization_id
                     AND rdv.request_definition_id = rd.id
                    WHERE rd.organization_id = :organization_id
                      AND rd.request_key = :request_key
                      AND rd.active = true
                    ORDER BY rdv.version DESC
                    LIMIT 1
                    """
                )
                parameters: dict[str, object] = {
                    "organization_id": organization_id,
                    "request_key": request_key,
                }
            else:
                statement = text(
                    """
                    SELECT rdv.id,
                           rd.request_key,
                           rdv.version
                    FROM request_engine.request_definitions AS rd
                    JOIN request_engine.request_definition_versions AS rdv
                      ON rdv.organization_id = rd.organization_id
                     AND rdv.request_definition_id = rd.id
                    WHERE rd.organization_id = :organization_id
                      AND rd.request_key = :request_key
                      AND rd.active = true
                      AND rdv.version = :version
                    LIMIT 1
                    """
                )
                parameters = {
                    "organization_id": organization_id,
                    "request_key": request_key,
                    "version": version,
                }

            row = ((await session.execute(statement, parameters)).mappings().first())

        if row is None:
            raise RequestDefinitionNotFound(request_key, version)
        return ResolvedRequestDefinitionVersion(
            id=cast(UUID, row["id"]),
            request_key=cast(str, row["request_key"]),
            version=cast(int, row["version"]),
        )
