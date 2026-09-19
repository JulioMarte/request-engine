from datetime import datetime
from uuid import UUID

from sqlalchemy import RowMapping, text
from sqlalchemy.exc import DBAPIError

from request_engine.modules.tenancy.adapters.db.integration_governance_commands import (
    raise_integration_db_error,
    require_integration_human_actor,
)
from request_engine.modules.tenancy.application.errors import IntegrationGovernanceNotFound
from request_engine.modules.tenancy.application.queries.integration_governance import (
    IntegrationCredentialSummary,
    IntegrationSummary,
    ListIntegrationsQuery,
)
from request_engine.modules.tenancy.domain.integration_governance import IntegrationStatus
from request_engine.platform.db.session import SessionFactory, actor_transaction
from request_engine.platform.security.context import ActorContext


def _summary(row: RowMapping) -> IntegrationSummary:
    return IntegrationSummary(
        principal_id=row["principal_id"],
        authority_revision=row["authority_revision"],
        status=IntegrationStatus(row["status"]),
        binding_id=row["binding_id"],
        workload_identity_id=row["workload_identity_id"],
        identity_authority_id=row["identity_authority_id"],
        capabilities=tuple(row["capabilities"]),
        credentials=tuple(
            IntegrationCredentialSummary(
                credential_id=UUID(credential["credential_id"]),
                status=credential["status"],
                expires_at=datetime.fromisoformat(credential["expires_at"]),
                created_at=datetime.fromisoformat(credential["created_at"]),
            )
            for credential in row["credentials"]
        ),
        provenance_complete=row["provenance_complete"],
    )


class PostgresIntegrationGovernanceReader:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def read_integration(self, actor: ActorContext, principal_id: UUID) -> IntegrationSummary:
        rows = await self._read(actor, principal_id=principal_id, after=None, limit=1)
        if not rows:
            raise IntegrationGovernanceNotFound(
                "integration Principal is not visible in this tenant"
            )
        return rows[0]

    async def list_integrations(
        self,
        actor: ActorContext,
        query: ListIntegrationsQuery,
    ) -> tuple[IntegrationSummary, ...]:
        if not 1 <= query.limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        return await self._read(actor, principal_id=None, after=query.after, limit=query.limit)

    async def _read(
        self,
        actor: ActorContext,
        *,
        principal_id: UUID | None,
        after: UUID | None,
        limit: int,
    ) -> tuple[IntegrationSummary, ...]:
        require_integration_human_actor(actor)
        async with actor_transaction(self._session_factory, actor) as session:
            try:
                result = await session.execute(
                    text("SELECT * FROM request_read.integrations(:principal_id, :after, :limit)"),
                    {"principal_id": principal_id, "after": after, "limit": limit},
                )
            except DBAPIError as exc:
                raise_integration_db_error(exc)
            return tuple(_summary(row) for row in result.mappings())
