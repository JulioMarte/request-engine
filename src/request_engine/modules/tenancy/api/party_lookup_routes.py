"""`parties.lookup` HTTP route: phone / document / display-name prefix lookup."""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from request_engine.modules.tenancy.api.party_registry_errors import PartyRegistryInputInvalid
from request_engine.modules.tenancy.api.party_registry_models import RegisteredPartyView
from request_engine.modules.tenancy.application.queries.lookup_parties import (
    PartyLookupMode,
    PartyLookupQuery,
    PartyLookupReader,
    lookup_parties,
)
from request_engine.modules.tenancy.domain.party_identity import PartyDocumentKind
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import require_capability

ActorDependency = Callable[[Request], Awaitable[ActorContext]]


def add_party_lookup_routes(
    router: APIRouter,
    *,
    lookup_reader: PartyLookupReader,
    authenticated_actor: ActorDependency,
) -> None:
    async def lookup_route(
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        mode: PartyLookupMode,
        value: str = Query(min_length=1),
        document_kind: str = PartyDocumentKind.CEDULA.value,
    ) -> tuple[RegisteredPartyView, ...]:
        require_capability(actor, "parties.lookup")
        try:
            parties = await lookup_parties(
                lookup_reader,
                PartyLookupQuery(
                    organization_id=actor.organization_id,
                    mode=mode,
                    value=value,
                    document_kind=document_kind,
                ),
            )
        except ValueError as error:
            raise PartyRegistryInputInvalid(str(error)) from None
        return tuple(RegisteredPartyView.from_contract(party) for party in parties)

    add_capability_route(
        router,
        "/lookup",
        lookup_route,
        capability="parties.lookup",
        methods=["GET"],
        response_model=tuple[RegisteredPartyView, ...],
        response_model_exclude_none=True,
    )
