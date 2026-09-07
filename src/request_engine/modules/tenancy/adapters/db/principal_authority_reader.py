from uuid import UUID

from sqlalchemy import text

from request_engine.platform.db.session import SessionFactory, set_tenant_context
from request_engine.platform.security.capabilities import capability_definition
from request_engine.platform.security.principal_authority import (
    PrincipalAuthorityMaterializationError,
    PrincipalAuthoritySnapshot,
)


class PostgresPrincipalAuthorityReader:
    """Materialize RE-owned standing authority from one PostgreSQL statement snapshot."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def read_tenant_principal_authority(
        self, *, organization_id: UUID, principal_id: UUID
    ) -> PrincipalAuthoritySnapshot | None:
        async with self._session_factory() as session, session.begin():
            await set_tenant_context(session, organization_id)
            rows = (
                (
                    await session.execute(
                        text(
                            """
                        SELECT p.principal_kind, p.active, p.principal_plane,
                               p.authority_revision, g.capability_key,
                               g.authority_plane, g.delegable
                          FROM request_engine.principals AS p
                          LEFT JOIN request_engine.principal_authority_grants AS g
                            ON g.principal_id = p.id
                           AND g.organization_id = p.organization_id
                           AND g.status = 'active'
                         WHERE p.organization_id = :organization_id
                           AND p.id = :principal_id
                         ORDER BY g.capability_key
                        """
                        ),
                        {"organization_id": organization_id, "principal_id": principal_id},
                    )
                )
                .mappings()
                .all()
            )
        if not rows:
            return None
        principal = rows[0]
        if not principal["active"] or principal["principal_plane"] != "tenant":
            return None

        capabilities: set[str] = set()
        delegable: set[str] = set()
        for row in rows:
            key = row["capability_key"]
            if key is None:
                continue
            definition = capability_definition(key)
            if definition is None:
                raise PrincipalAuthorityMaterializationError(f"unknown persisted capability: {key}")
            if row["authority_plane"] != definition.authority_plane.value:
                raise PrincipalAuthorityMaterializationError(
                    f"authority plane mismatch for persisted capability: {key}"
                )
            capabilities.add(key)
            if row["delegable"]:
                delegable.add(key)

        return PrincipalAuthoritySnapshot(
            principal_id=principal_id,
            principal_kind=str(principal["principal_kind"]),
            authority_revision=int(principal["authority_revision"]),
            capabilities=frozenset(capabilities),
            delegable_capabilities=frozenset(delegable),
        )
