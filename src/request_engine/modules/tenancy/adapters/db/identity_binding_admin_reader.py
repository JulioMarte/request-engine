from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.tenancy.application.queries.identity_binding import (
    IDENTITY_BINDING_READ_CAPABILITY,
    GetIdentityBindingQuery,
    IdentityBindingNotFound,
    IdentityBindingReadForbidden,
    IdentityBindingView,
    ListIdentityBindingsQuery,
)
from request_engine.platform.db.session import SessionFactory, actor_transaction
from request_engine.platform.security.context import ActorContext, PrincipalKind

_BINDING_PROJECTION = """
    SELECT access.permitted, binding.*
      FROM (SELECT EXISTS (
          SELECT 1 FROM request_engine.principals actor
          JOIN request_engine.staff_memberships membership
            ON membership.organization_id = actor.organization_id
           AND membership.principal_id = actor.id AND membership.status = 'active'
          JOIN request_engine.principal_authority_grants grant_row
            ON grant_row.organization_id = actor.organization_id
           AND grant_row.principal_id = actor.id
           AND grant_row.capability_key = :capability
           AND grant_row.authority_plane = 'tenant_control'
           AND grant_row.status = 'active'
         WHERE actor.organization_id = :organization_id AND actor.id = :actor_id
           AND actor.active AND actor.principal_kind = 'human'
      ) AS permitted) access
      LEFT JOIN LATERAL (
          SELECT binding.id AS binding_id, binding.principal_id,
                 binding.identity_authority_id,
                 binding.status, binding.revision, binding.created_at
            FROM request_engine.identity_bindings binding
           WHERE access.permitted AND binding.organization_id = :organization_id
             AND binding.principal_plane = 'tenant'
             AND (CAST(:binding_id AS uuid) IS NULL OR binding.id = :binding_id)
             AND (CAST(:principal_id AS uuid) IS NULL OR binding.principal_id = :principal_id)
             AND (CAST(:status AS text) IS NULL OR binding.status = :status)
             AND (CAST(:after AS uuid) IS NULL OR binding.id > :after)
           ORDER BY binding.id LIMIT :limit
      ) binding ON true
     ORDER BY binding.binding_id
"""


class PostgresIdentityBindingAdminReader:
    """Inspect tenant identity bindings under the actor's current read authority.

    Authorization and the row set share one statement snapshot, so there is no
    check/read race. Tenant RLS keeps the projection scoped to the actor's
    Organization; a foreign or absent binding is indistinguishable.
    """

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def list_bindings(
        self,
        actor: ActorContext,
        query: ListIdentityBindingsQuery,
    ) -> tuple[IdentityBindingView, ...]:
        rows = await self._read(
            actor,
            binding_id=None,
            principal_id=query.principal_id,
            status=query.status,
            after=query.after,
            limit=query.limit,
        )
        return tuple(_materialize(row) for row in rows)

    async def read_binding(
        self,
        actor: ActorContext,
        query: GetIdentityBindingQuery,
    ) -> IdentityBindingView:
        rows = await self._read(
            actor,
            binding_id=query.binding_id,
            principal_id=None,
            status=None,
            after=None,
            limit=1,
        )
        if not rows:
            raise IdentityBindingNotFound("identity binding is not visible in this tenant")
        return _materialize(rows[0])

    async def _read(
        self,
        actor: ActorContext,
        *,
        binding_id: UUID | None,
        principal_id: UUID | None,
        status: str | None,
        after: UUID | None,
        limit: int,
    ) -> list[Mapping[str, Any]]:
        if actor.principal_kind is not PrincipalKind.HUMAN:
            raise IdentityBindingReadForbidden("identity binding inspection requires a HUMAN actor")
        async with actor_transaction(self._session_factory, actor) as session:
            rows = (
                (
                    await session.execute(
                        text(_BINDING_PROJECTION),
                        {
                            "capability": IDENTITY_BINDING_READ_CAPABILITY,
                            "organization_id": actor.organization_id,
                            "actor_id": actor.principal_id,
                            "binding_id": binding_id,
                            "principal_id": principal_id,
                            "status": status,
                            "after": after,
                            "limit": limit,
                        },
                    )
                )
                .mappings()
                .all()
            )
        if not rows[0]["permitted"]:
            raise IdentityBindingReadForbidden("identity binding inspection authority was denied")
        return [dict(row) for row in rows if row["binding_id"] is not None]


def _materialize(row: Mapping[str, Any]) -> IdentityBindingView:
    return IdentityBindingView(
        binding_id=UUID(str(row["binding_id"])),
        principal_id=UUID(str(row["principal_id"])),
        identity_authority_id=UUID(str(row["identity_authority_id"])),
        status=str(row["status"]),
        revision=int(row["revision"]),
        created_at=row["created_at"],
    )
