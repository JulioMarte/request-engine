from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import text

from request_engine.platform.db.session import SessionFactory, set_tenant_context
from request_engine.platform.security.capabilities import capability_definition
from request_engine.platform.security.capability_types import AuthorityPlane
from request_engine.platform.security.principal_authority import (
    PrincipalAuthorityMaterializationError,
    PrincipalAuthoritySnapshot,
    PrincipalAuthorityReader,
)


def materialize_tenant_authority(
    *, principal_id: UUID, rows: Sequence[Mapping[str, Any]]
) -> PrincipalAuthoritySnapshot | None:
    if not rows:
        return None
    principal = rows[0]
    if not principal["active"]:
        return None

    capabilities: set[str] = set()
    delegable: set[str] = set()
    for row in rows:
        key = row["capability_key"]
        if key is None:
            continue
        definition = capability_definition(str(key))
        if definition is None:
            raise PrincipalAuthorityMaterializationError(f"unknown persisted capability: {key}")
        if definition.authority_plane is AuthorityPlane.PLATFORM:
            raise PrincipalAuthorityMaterializationError(
                f"platform capability returned by tenant authority boundary: {key}"
            )
        capabilities.add(str(key))
        if row["delegable"]:
            delegable.add(str(key))

    return PrincipalAuthoritySnapshot(
        principal_id=principal_id,
        principal_kind=str(principal["principal_kind"]),
        authority_revision=int(principal["authority_revision"]),
        capabilities=frozenset(capabilities),
        delegable_capabilities=frozenset(delegable),
    )


class PostgresTenantPrincipalAuthorityReader(PrincipalAuthorityReader):
    """Read current tenant authority under the tenant RLS boundary."""

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
                            SELECT p.principal_kind,
                                   p.active,
                                   p.authority_revision,
                                   g.capability_key,
                                   g.delegable
                              FROM request_engine.principals AS p
                              LEFT JOIN request_engine.principal_authority_grants AS g
                                ON g.principal_id = p.id
                               AND g.organization_id = p.organization_id
                               AND g.principal_plane = 'tenant'
                               AND g.status = 'active'
                             WHERE p.id = :principal_id
                               AND p.organization_id = :organization_id
                               AND p.principal_plane = 'tenant'
                            """
                        ),
                        {
                            "principal_id": principal_id,
                            "organization_id": organization_id,
                        },
                    )
                )
                .mappings()
                .all()
            )

        normalized_rows: list[dict[str, Any]] = [
            {
                "principal_kind": row["principal_kind"],
                "active": row["active"],
                "authority_revision": row["authority_revision"],
                "capability_key": row["capability_key"],
                "delegable": row["delegable"],
            }
            for row in rows
        ]
        return materialize_tenant_authority(
            principal_id=principal_id,
            rows=normalized_rows,
        )
