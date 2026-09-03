"""HTTP routes for tenant-owned Party administrative identifiers."""

from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from request_engine.modules.tenancy.api.party_administrative_identifier_models import (
    AddPartyAdministrativeIdentifierBody,
    PartyAdministrativeIdentifierView,
)
from request_engine.modules.tenancy.api.party_registry_dependencies import (
    IdempotencyKey,
    source_kind,
)
from request_engine.modules.tenancy.api.party_registry_errors import PartyRegistryInputInvalid
from request_engine.modules.tenancy.api.party_registry_models import RegisteredPartyView
from request_engine.modules.tenancy.application.commands import (
    add_party_administrative_identifier as admin_identifier_commands,
)
from request_engine.modules.tenancy.application.queries.party_administrative_identifiers import (
    PartyAdministrativeIdentifierListQuery,
    PartyAdministrativeIdentifierLookupQuery,
    PartyAdministrativeIdentifierReader,
    lookup_party_by_administrative_identifier,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import require_capability

ActorDependency = Callable[[Request], Awaitable[ActorContext]]
_READ_CAPABILITY = "parties.lookup_administrative_identifier"


def add_party_administrative_identifier_routes(
    router: APIRouter,
    *,
    add_handler: admin_identifier_commands.AddPartyAdministrativeIdentifierHandler,
    reader: PartyAdministrativeIdentifierReader,
    authenticated_actor: ActorDependency,
) -> None:
    async def add_route(
        party_id: UUID,
        body: AddPartyAdministrativeIdentifierBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> PartyAdministrativeIdentifierView:
        require_capability(actor, "parties.add_administrative_identifier")
        try:
            identifier = await admin_identifier_commands.add_party_administrative_identifier(
                add_handler,
                admin_identifier_commands.AddPartyAdministrativeIdentifierCommand(
                    organization_id=actor.organization_id,
                    principal_id=actor.principal_id,
                    party_id=party_id,
                    kind=body.kind,
                    issuer=body.issuer,
                    value=body.value,
                    source_kind=source_kind(actor),
                    idempotency_key=idempotency_key,
                    platform=actor.platform,
                    technical_principal_id=actor.technical_principal_id,
                ),
            )
        except ValueError as error:
            raise PartyRegistryInputInvalid(str(error)) from None
        return PartyAdministrativeIdentifierView.from_contract(identifier)

    async def list_route(
        party_id: UUID,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
    ) -> tuple[PartyAdministrativeIdentifierView, ...]:
        require_capability(actor, _READ_CAPABILITY)
        identifiers = await reader.list_for_party(
            PartyAdministrativeIdentifierListQuery(actor.organization_id, party_id)
        )
        return tuple(PartyAdministrativeIdentifierView.from_contract(item) for item in identifiers)

    async def lookup_route(
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        kind: str = Query(min_length=1, max_length=64),
        issuer: str = Query(min_length=1, max_length=128),
        value: str = Query(min_length=1, max_length=256),
    ) -> tuple[RegisteredPartyView, ...]:
        require_capability(actor, _READ_CAPABILITY)
        try:
            query = PartyAdministrativeIdentifierLookupQuery(
                actor.organization_id,
                kind,
                issuer,
                value,
            )
            parties = await lookup_party_by_administrative_identifier(reader, query)
        except ValueError as error:
            raise PartyRegistryInputInvalid(str(error)) from None
        return tuple(RegisteredPartyView.from_contract(party) for party in parties)

    add_capability_route(
        router,
        "/{party_id}/administrative-identifiers",
        add_route,
        capability="parties.add_administrative_identifier",
        methods=["POST"],
        response_model=PartyAdministrativeIdentifierView,
        status_code=status.HTTP_201_CREATED,
    )
    add_capability_route(
        router,
        "/{party_id}/administrative-identifiers",
        list_route,
        capability=_READ_CAPABILITY,
        methods=["GET"],
        operation_id="parties_list_administrative_identifiers",
        response_model=tuple[PartyAdministrativeIdentifierView, ...],
    )
    add_capability_route(
        router,
        "/lookup/administrative-identifier",
        lookup_route,
        capability=_READ_CAPABILITY,
        methods=["GET"],
        operation_id="parties_lookup_administrative_identifier",
        response_model=tuple[RegisteredPartyView, ...],
    )
