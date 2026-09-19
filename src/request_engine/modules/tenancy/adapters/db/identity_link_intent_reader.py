from uuid import UUID

from sqlalchemy import text

from request_engine.modules.tenancy.application.queries.identity_link import (
    IdentityLinkIntentSnapshot,
)
from request_engine.platform.db.session import SessionFactory, actor_transaction
from request_engine.platform.security.context import ActorContext


class PostgresIdentityLinkIntentReader:
    """Read one persisted link intent under the actor's current tenant context.

    The definer function is tenant-scoped, so a foreign organization's intent is
    indistinguishable from an absent one. The caller still verifies the actor
    owns the returned intent before deriving any authority from it.
    """

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def read_intent(
        self,
        actor: ActorContext,
        *,
        intent_id: UUID,
    ) -> IdentityLinkIntentSnapshot | None:
        async with actor_transaction(self._session_factory, actor) as session:
            row = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT intent_id,
                                   actor_principal_id,
                                   target_authority_id,
                                   target_authority_kind,
                                   actor_binding_revision,
                                   status,
                                   expires_at
                              FROM request_engine.read_identity_link_intent(:intent_id)
                            """
                        ),
                        {"intent_id": intent_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return IdentityLinkIntentSnapshot(
            intent_id=UUID(str(row["intent_id"])),
            actor_principal_id=UUID(str(row["actor_principal_id"])),
            target_authority_id=UUID(str(row["target_authority_id"])),
            target_authority_kind=str(row["target_authority_kind"]),
            actor_binding_revision=int(row["actor_binding_revision"]),
            status=str(row["status"]),
            expires_at=row["expires_at"],
        )
