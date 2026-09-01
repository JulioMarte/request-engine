"""`parties.add_contact_point` and `parties.confirm_contact_point` HTTP routes."""

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
    AddPartyContactPointBody,
    PartyContactPointView,
)
from request_engine.modules.tenancy.application.commands.add_party_contact_point import (
    AddPartyContactPointCommand,
    AddPartyContactPointHandler,
    add_party_contact_point,
)
from request_engine.modules.tenancy.application.commands.confirm_party_contact_point import (
    ConfirmPartyContactPointCommand,
    ConfirmPartyContactPointHandler,
    confirm_party_contact_point,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import require_capability

ActorDependency = Callable[[Request], Awaitable[ActorContext]]


def add_party_contact_point_routes(
    router: APIRouter,
    *,
    add_contact_point_handler: AddPartyContactPointHandler,
    confirm_handler: ConfirmPartyContactPointHandler,
    authenticated_actor: ActorDependency,
) -> None:
    async def add_contact_point_route(
        party_id: UUID,
        body: AddPartyContactPointBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> PartyContactPointView:
        require_capability(actor, "parties.add_contact_point")
        try:
            contact_point = await add_party_contact_point(
                add_contact_point_handler,
                AddPartyContactPointCommand(
                    organization_id=actor.organization_id,
                    principal_id=actor.principal_id,
                    party_id=party_id,
                    channel=body.channel,
                    value=body.value,
                    source_kind=source_kind(actor),
                    idempotency_key=idempotency_key,
                    platform=actor.platform,
                    technical_principal_id=actor.technical_principal_id,
                ),
            )
        except ValueError as error:
            raise PartyRegistryInputInvalid(str(error)) from None
        return PartyContactPointView.from_contract(contact_point)

    async def confirm_contact_point_route(
        party_id: UUID,
        contact_point_id: UUID,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> PartyContactPointView:
        require_capability(actor, "parties.confirm_contact_point")
        contact_point = await confirm_party_contact_point(
            confirm_handler,
            ConfirmPartyContactPointCommand(
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

    add_capability_route(
        router,
        "/{party_id}/contact-points",
        add_contact_point_route,
        capability="parties.add_contact_point",
        methods=["POST"],
        response_model=PartyContactPointView,
        status_code=status.HTTP_201_CREATED,
    )
    add_capability_route(
        router,
        "/{party_id}/contact-points/{contact_point_id}/confirm",
        confirm_contact_point_route,
        capability="parties.confirm_contact_point",
        methods=["POST"],
        response_model=PartyContactPointView,
    )
