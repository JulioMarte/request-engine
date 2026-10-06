from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from request_engine.modules.tenancy.application.queries.platform_owner_read import (
    PlatformOwnerInvitationSummary,
    PlatformOwnerReadForbidden,
    PlatformOwnerReadQuery,
    PlatformOwnerSummary,
)
from request_engine.platform.db.session import SessionFactory, platform_actor_transaction
from request_engine.platform.security.context import PrincipalKind
from request_engine.platform.security.platform_context import PlatformActorContext


class PostgresPlatformOwnerReader:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def read_owners(
        self, actor: PlatformActorContext, query: PlatformOwnerReadQuery
    ) -> tuple[PlatformOwnerSummary, ...]:
        rows = await self._read(actor, query, invitations=False)
        return tuple(
            PlatformOwnerSummary(
                principal_id=row[0],
                active=row[1],
                authority_revision=row[2],
                binding_id=row[3],
                binding_status=row[4],
                capabilities=tuple(row[5]),
            )
            for row in rows
        )

    async def read_invitations(
        self, actor: PlatformActorContext, query: PlatformOwnerReadQuery
    ) -> tuple[PlatformOwnerInvitationSummary, ...]:
        rows = await self._read(actor, query, invitations=True)
        return tuple(PlatformOwnerInvitationSummary(*row) for row in rows)

    async def _read(
        self, actor: PlatformActorContext, query: PlatformOwnerReadQuery, *, invitations: bool
    ) -> list[tuple[Any, ...]]:
        if actor.principal_kind is not PrincipalKind.HUMAN or not actor.allows(
            "platform.owner.read"
        ):
            raise PlatformOwnerReadForbidden()
        # Function selection is closed server-owned policy, never caller-provided SQL.
        function = "read_platform_owner_invitations" if invitations else "read_platform_owners"
        try:
            async with platform_actor_transaction(self._session_factory, actor) as session:
                result = await session.execute(
                    text(
                        f"SELECT * FROM request_platform.{function}("
                        "CAST(:resource_id AS uuid), CAST(:after AS uuid), CAST(:limit AS integer))"
                    ),
                    {"resource_id": query.resource_id, "after": query.after, "limit": query.limit},
                )
                return [tuple(row) for row in result.all()]
        except DBAPIError as exc:
            if str(getattr(exc.orig, "sqlstate", "")) in {"42501", "28000", "40001"}:
                raise PlatformOwnerReadForbidden() from None
            raise
