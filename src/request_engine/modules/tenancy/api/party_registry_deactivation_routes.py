"""Operator-granted party deactivation routes (`parties.deactivate_contact_point`,
`parties.deactivate`).

Transport route handlers map path identifiers verbatim into application
commands; the deactivation capabilities are grant-gated like every other
party registry command and are never granted to bot principals.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from request_engine.modules.tenancy.api.party_registry_dependencies import (
    IdempotencyKey,
    source_kind,
)
from request_engine.modules.tenancy.api.party_registry_models import (
    PartyContactPointView,
    RegisteredPartyView,
)
from request_engine.modules.tenancy.application.commands import (
    deactivate_party,
    deactivate_party_contact_point,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import require_capability

ActorDependency = Callable[[Request], Awaitable[ActorContext]]


def add_party_deactivation_routes(
    router: APIRouter,
    *,
    deactivate_contact_point_handler: (
        deactivate_party_contact_point.DeactivatePartyContactPointHandler
    ),
    deactivate_party_handler: deactivate_party.DeactivatePartyHandler,
    authenticated_actor: ActorDependency,
) -> None:
    async def deactivate_contact_point_route(
        party_id: UUID,
        contact_point_id: UUID,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> PartyContactPointView:
        require_capability(actor, "parties.deactivate_contact_point")
        contact_point = await deactivate_party_contact_point.deactivate_party_contact_point(
            deactivate_contact_point_handler,
            deactivate_party_contact_point.DeactivatePartyContactPointCommand(
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                party_id=party_id,
                contact_point_id=contact_point_id,
                idempotency_key=idempotency_key,
                source_kind=source_kind(actor),
                platform=actor.platform,
                technical_principal_id=actor.technical_principal_id,
            ),
        )
        return PartyContactPointView.from_contract(contact_point)

    async def deactivate_party_route(
        party_id: UUID,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> RegisteredPartyView:
        require_capability(actor, "parties.deactivate")
        party = await deactivate_party.deactivate_party(
            deactivate_party_handler,
            deactivate_party.DeactivatePartyCommand(
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                party_id=party_id,
                idempotency_key=idempotency_key,
                source_kind=source_kind(actor),
                platform=actor.platform,
                technical_principal_id=actor.technical_principal_id,
            ),
        )
        return RegisteredPartyView.from_contract(party)

    add_capability_route(
        router,
        "/{party_id}/contact-points/{contact_point_id}/deactivate",
        deactivate_contact_point_route,
        capability="parties.deactivate_contact_point",
        methods=["POST"],
        response_model=PartyContactPointView,
    )
    add_capability_route(
        router,
        "/{party_id}/deactivate",
        deactivate_party_route,
        capability="parties.deactivate",
        methods=["POST"],
        response_model=RegisteredPartyView,
    )
