from uuid import UUID

from sqlalchemy import text

from request_engine.platform.db.session import SessionFactory, tenant_transaction


class PostgresBusinessPartyReader:
    """Tenancy-owned read: does the tenant have its own active organization Party?"""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def has_active_organization_party(
        self,
        *,
        organization_id: UUID,
    ) -> bool:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            row = await session.execute(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM request_engine.parties
                        WHERE organization_id = :organization_id
                          AND party_kind = 'organization'
                          AND active
                    )
                    """
                ),
                {"organization_id": organization_id},
            )
            return bool(row.scalar_one())
