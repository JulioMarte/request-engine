from typing import Any

from sqlalchemy import text

from request_engine.platform.db.session import SessionFactory, set_tenant_context
from request_engine.platform.security.delegation import (
    DelegationSnapshot,
    DelegationStatus,
)


class PostgresDelegationReader:
    """Tenant-scoped delegation and delegator-authority reads under RLS."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def read_delegation(
        self, *, organization_id: Any, delegation_id: Any
    ) -> DelegationSnapshot | None:
        async with self._session_factory() as session, session.begin():
            await set_tenant_context(session, organization_id)
            row = (
                await session.execute(
                    text(
                        """
                        SELECT id, organization_id, delegator_principal_id,
                               delegate_principal_id, allowed_capabilities,
                               status, not_before, expires_at
                          FROM request_engine.delegations
                         WHERE id = :delegation_id
                        """
                    ),
                    {"delegation_id": delegation_id},
                )
            ).fetchone()
        if row is None:
            return None
        return DelegationSnapshot(
            delegation_id=row[0],
            organization_id=row[1],
            delegator_principal_id=row[2],
            delegate_principal_id=row[3],
            allowed_capabilities=frozenset(row[4]),
            status=DelegationStatus(row[5]),
            not_before=row[6],
            expires_at=row[7],
        )

    async def read_delegator_delegable_capabilities(
        self, *, organization_id: Any, principal_id: Any
    ) -> frozenset[str]:
        async with self._session_factory() as session, session.begin():
            await set_tenant_context(session, organization_id)
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT capability_key
                          FROM request_engine.principal_authority_grants
                         WHERE organization_id = :organization_id
                           AND principal_id = :principal_id
                           AND principal_plane = 'tenant'
                           AND authority_plane = 'operational'
                           AND status = 'active'
                           AND delegable
                        """
                    ),
                    {
                        "organization_id": organization_id,
                        "principal_id": principal_id,
                    },
                )
            ).fetchall()
        return frozenset(row[0] for row in rows)
