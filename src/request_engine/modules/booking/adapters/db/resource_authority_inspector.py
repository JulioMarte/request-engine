from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.application.authority import (
    BOOK_APPOINTMENT_SCOPE,
    SUBJECT_OVERRIDE_PERMISSION,
)
from request_engine.modules.tenancy.contracts.resource_authority import (
    ResourceAuthorityDecision,
    ResourceAuthorityDecisionKind,
    ResourceAuthorityOperation,
    ResourceAuthorityQuery,
    ResourceAuthorityTargetNotFound,
)
from request_engine.platform.db.session import SessionFactory, actor_transaction
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.operational_authority import (
    MANAGE_CONTEXTUAL_SUPPLY_SCOPE,
)

_CURRENT_REPRESENTATION = "current_representation"
_OPERATOR_OVERRIDE = "operator_override"
_NO_CURRENT_REPRESENTATION = "no_current_representation"
_ACTOR_AUTHORITY_UNAVAILABLE = "actor_authority_unavailable"


class PostgresResourceAuthorityInspector:
    """Read-only owner inspection reusing the booking authority primitive.

    No locks, no writes, no idempotency receipt: a single statement snapshot
    resolves the actor's current authority revision and the current exact-scope
    Representation exactly as the booking commands do, without their write locks.
    """

    supported_operations = frozenset(
        {
            ResourceAuthorityOperation.APPOINTMENTS_BOOK.value,
            ResourceAuthorityOperation.BOOKING_MANAGE_SUPPLY.value,
        }
    )

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def inspect(
        self, actor: ActorContext, query: ResourceAuthorityQuery
    ) -> ResourceAuthorityDecision:
        if query.operation.value not in self.supported_operations:
            raise ValueError(f"unsupported resource authority operation {query.operation.value!r}")
        async with actor_transaction(self._session_factory, actor) as session:
            authority_revision = await _actor_authority_revision(session, actor)
            if authority_revision is None:
                return ResourceAuthorityDecision(
                    decision=ResourceAuthorityDecisionKind.INDETERMINATE,
                    reason_codes=(_ACTOR_AUTHORITY_UNAVAILABLE,),
                    authority_revision=0,
                )
            return await self._inspect(session, actor, query, authority_revision)

    async def _inspect(
        self,
        session: AsyncSession,
        actor: ActorContext,
        query: ResourceAuthorityQuery,
        authority_revision: int,
    ) -> ResourceAuthorityDecision:
        if query.operation is ResourceAuthorityOperation.APPOINTMENTS_BOOK:
            party_id = cast(UUID, query.subject_party_id)
            if not await _party_visible(session, actor.organization_id, party_id):
                raise ResourceAuthorityTargetNotFound(str(party_id))
            if actor.allows(SUBJECT_OVERRIDE_PERMISSION):
                return ResourceAuthorityDecision(
                    decision=ResourceAuthorityDecisionKind.ALLOWED,
                    reason_codes=(_OPERATOR_OVERRIDE,),
                    authority_revision=authority_revision,
                )
            scope_key = BOOK_APPOINTMENT_SCOPE
        else:
            party_id = cast(UUID, query.authority_party_id)
            if not await _party_visible(session, actor.organization_id, party_id):
                raise ResourceAuthorityTargetNotFound(str(party_id))
            scope_key = MANAGE_CONTEXTUAL_SUPPLY_SCOPE

        representation_revision = await _resolve_representation(session, actor, party_id, scope_key)
        if representation_revision is None:
            return ResourceAuthorityDecision(
                decision=ResourceAuthorityDecisionKind.DENIED,
                reason_codes=(_NO_CURRENT_REPRESENTATION,),
                authority_revision=authority_revision,
            )
        return ResourceAuthorityDecision(
            decision=ResourceAuthorityDecisionKind.ALLOWED,
            reason_codes=(_CURRENT_REPRESENTATION,),
            authority_revision=authority_revision,
            representation_revision=representation_revision,
        )


async def _actor_authority_revision(session: AsyncSession, actor: ActorContext) -> int | None:
    row = (
        await session.execute(
            text(
                """
                SELECT authority_revision
                FROM request_engine.principals
                WHERE organization_id = :organization_id AND id = :principal_id AND active
                """
            ),
            {"organization_id": actor.organization_id, "principal_id": actor.principal_id},
        )
    ).scalar_one_or_none()
    return None if row is None else int(row)


async def _party_visible(session: AsyncSession, organization_id: UUID, party_id: UUID) -> bool:
    row = (
        await session.execute(
            text(
                """
                SELECT 1
                FROM request_engine.parties
                WHERE organization_id = :organization_id AND id = :party_id
                """
            ),
            {"organization_id": organization_id, "party_id": party_id},
        )
    ).scalar_one_or_none()
    return row is not None


async def _resolve_representation(
    session: AsyncSession,
    actor: ActorContext,
    party_id: UUID,
    scope_key: str,
) -> int | None:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT representation.revision
                    FROM request_engine.resolve_current_party_authority(
                        :organization_id, :principal_id, :party_id, :scope_key
                    ) AS authority
                    JOIN request_engine.representations AS representation
                      ON representation.id = authority.representation_id
                    """
                ),
                {
                    "organization_id": actor.organization_id,
                    "principal_id": actor.principal_id,
                    "party_id": party_id,
                    "scope_key": scope_key,
                },
            )
        )
        .scalars()
        .first()
    )
    return None if row is None else int(row)
