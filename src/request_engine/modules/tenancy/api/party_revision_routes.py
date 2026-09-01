"""Party revision history and rollback routes (`parties.read_revisions`,
`parties.rollback_identity`).

The history read is org-scoped and grant-gated; a foreign Party resolves to
the typed not-found. Rollback maps the body's `target_revision` verbatim into
the application command; both capabilities are grant-gated like every other
party registry capability and are never granted to bot principals.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from request_engine.modules.tenancy.api.party_registry_dependencies import (
    IdempotencyKey,
    source_kind,
)
from request_engine.modules.tenancy.api.party_registry_errors import PartyRegistryInputInvalid
from request_engine.modules.tenancy.api.party_registry_models import (
    PartyRevisionView,
    RegisteredPartyView,
    RollbackPartyBody,
)
from request_engine.modules.tenancy.application.commands.rollback_party_identity import (
    RollbackPartyIdentityCommand,
    RollbackPartyIdentityHandler,
    rollback_party_identity,
)
from request_engine.modules.tenancy.application.queries.party_revision_history import (
    PartyRevisionHistoryQuery,
    PartyRevisionHistoryReader,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import require_capability

ActorDependency = Callable[[Request], Awaitable[ActorContext]]


def add_party_revision_routes(
    router: APIRouter,
    *,
    revision_history_reader: PartyRevisionHistoryReader,
    rollback_handler: RollbackPartyIdentityHandler,
    authenticated_actor: ActorDependency,
) -> None:
    async def revisions_route(
        party_id: UUID,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
    ) -> tuple[PartyRevisionView, ...]:
        require_capability(actor, "parties.read_revisions")
        revisions = await revision_history_reader.revision_history(
            PartyRevisionHistoryQuery(
                organization_id=actor.organization_id,
                party_id=party_id,
            )
        )
        return tuple(PartyRevisionView.from_contract(revision) for revision in revisions)

    async def rollback_route(
        party_id: UUID,
        body: RollbackPartyBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> RegisteredPartyView:
        require_capability(actor, "parties.rollback_identity")
        try:
            party = await rollback_party_identity(
                rollback_handler,
                RollbackPartyIdentityCommand(
                    organization_id=actor.organization_id,
                    principal_id=actor.principal_id,
                    party_id=party_id,
                    target_revision=body.target_revision,
                    idempotency_key=idempotency_key,
                    source_kind=source_kind(actor),
                    platform=actor.platform,
                    technical_principal_id=actor.technical_principal_id,
                ),
            )
        except ValueError as error:
            raise PartyRegistryInputInvalid(str(error)) from None
        return RegisteredPartyView.from_contract(party)

    add_capability_route(
        router,
        "/{party_id}/revisions",
        revisions_route,
        capability="parties.read_revisions",
        methods=["GET"],
        response_model=tuple[PartyRevisionView, ...],
        response_model_exclude_none=True,
    )
    add_capability_route(
        router,
        "/{party_id}/rollback",
        rollback_route,
        capability="parties.rollback_identity",
        methods=["POST"],
        response_model=RegisteredPartyView,
        status_code=status.HTTP_200_OK,
    )
