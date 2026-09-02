"""Public tenancy party registry HTTP surface composition (`parties.*`)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from request_engine.modules.tenancy.api.party_contact_point_routes import (
    add_party_contact_point_routes,
)
from request_engine.modules.tenancy.api.party_lookup_routes import add_party_lookup_routes
from request_engine.modules.tenancy.api.party_registry_dependencies import (
    IdempotencyKey,
    source_kind,
)
from request_engine.modules.tenancy.api.party_registry_errors import (
    PartyRegistryInputInvalid,
)
from request_engine.modules.tenancy.api.party_registry_models import (
    RegisteredPartyView,
    RegisterPartyBody,
)
from request_engine.modules.tenancy.application.commands.add_party_contact_point import (
    AddPartyContactPointHandler,
)
from request_engine.modules.tenancy.application.commands.confirm_party_contact_point import (
    ConfirmPartyContactPointHandler,
)
from request_engine.modules.tenancy.application.commands.register_party import (
    RegisterPartyCommand,
    RegisterPartyHandler,
    register_party,
)
from request_engine.modules.tenancy.application.queries.lookup_parties import PartyLookupReader
from request_engine.modules.tenancy.contracts.party_registry import (
    PartyContactPointInput,
    PartyDocumentInput,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability


def add_party_registry_routes(
    router: APIRouter,
    *,
    register_handler: RegisterPartyHandler,
    add_contact_point_handler: AddPartyContactPointHandler,
    confirm_handler: ConfirmPartyContactPointHandler,
    lookup_reader: PartyLookupReader,
    actor_resolver: ActorResolver,
) -> None:
    async def authenticated_actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def register_party_route(
        body: RegisterPartyBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> RegisteredPartyView:
        require_capability(actor, "parties.register")
        try:
            party = await register_party(
                register_handler,
                RegisterPartyCommand(
                    organization_id=actor.organization_id,
                    principal_id=actor.principal_id,
                    party_kind=body.party_kind,
                    display_name=body.display_name,
                    source_kind=source_kind(actor),
                    idempotency_key=idempotency_key,
                    contact_points=tuple(
                        PartyContactPointInput(item.channel, item.value)
                        for item in body.contact_points
                    ),
                    documents=tuple(
                        PartyDocumentInput(item.kind, item.value, item.authority)
                        for item in body.documents
                    ),
                    platform=actor.platform,
                    technical_principal_id=actor.technical_principal_id,
                ),
            )
        except ValueError as error:
            raise PartyRegistryInputInvalid(str(error)) from None
        return RegisteredPartyView.from_contract(party)

    add_capability_route(
        router,
        "",
        register_party_route,
        capability="parties.register",
        methods=["POST"],
        response_model=RegisteredPartyView,
        status_code=status.HTTP_201_CREATED,
    )
    add_party_contact_point_routes(
        router,
        add_contact_point_handler=add_contact_point_handler,
        confirm_handler=confirm_handler,
        authenticated_actor=authenticated_actor,
    )
    add_party_lookup_routes(
        router,
        lookup_reader=lookup_reader,
        authenticated_actor=authenticated_actor,
    )
