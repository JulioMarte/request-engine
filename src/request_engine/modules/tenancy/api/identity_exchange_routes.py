"""Opaque match and consented adoption routes for S0d identity exchange."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from request_engine.modules.tenancy.api.identity_exchange_dependencies import (
    require_operator_document_witness,
)
from request_engine.modules.tenancy.api.identity_exchange_errors import (
    IdentityExchangeInputInvalid,
)
from request_engine.modules.tenancy.api.identity_exchange_models import (
    IdentityAdoptionBody,
    IdentityAdoptionView,
    IdentityMatchBody,
    IdentityMatchView,
)
from request_engine.modules.tenancy.api.party_registry_dependencies import (
    IdempotencyKey,
    source_kind,
)
from request_engine.modules.tenancy.application.identity_exchange import (
    AdoptPortableIdentityCommand,
    AdoptPortableIdentityHandler,
    MatchPortableIdentityCommand,
    MatchPortableIdentityHandler,
    adopt_portable_identity,
    match_portable_identity,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability

_MATCH = "identity_exchange.match"
_ADOPT = "identity_exchange.adopt"


def add_identity_exchange_routes(
    router: APIRouter,
    *,
    matcher: MatchPortableIdentityHandler,
    adopter: AdoptPortableIdentityHandler,
    actor_resolver: ActorResolver,
) -> None:
    async def authenticated_actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def match_route(
        body: IdentityMatchBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> IdentityMatchView:
        require_capability(actor, _MATCH)
        require_operator_document_witness(actor)
        try:
            result = await match_portable_identity(
                matcher,
                MatchPortableIdentityCommand(
                    organization_id=actor.organization_id,
                    principal_id=actor.principal_id,
                    document_kind=body.document_kind,
                    document_authority=body.document_authority,
                    document_value=body.document_value,
                    proof_kind=body.proof_kind,
                    idempotency_key=idempotency_key,
                ),
            )
        except ValueError as error:
            raise IdentityExchangeInputInvalid(str(error)) from None
        return IdentityMatchView(matched=result.matched, candidate_ref=result.candidate_ref)

    async def adopt_route(
        body: IdentityAdoptionBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> IdentityAdoptionView:
        require_capability(actor, _ADOPT)
        require_operator_document_witness(actor)
        try:
            result = await adopt_portable_identity(
                adopter,
                AdoptPortableIdentityCommand(
                    organization_id=actor.organization_id,
                    principal_id=actor.principal_id,
                    candidate_ref=body.candidate_ref,
                    document_kind=body.document_kind,
                    document_authority=body.document_authority,
                    document_value=body.document_value,
                    consented_fields=body.consented_fields,
                    proof_kind=body.proof_kind,
                    idempotency_key=idempotency_key,
                    source_kind=source_kind(actor),
                    platform=actor.platform,
                    technical_principal_id=actor.technical_principal_id,
                ),
            )
        except ValueError as error:
            raise IdentityExchangeInputInvalid(str(error)) from None
        return IdentityAdoptionView.from_contract(result)

    add_capability_route(
        router,
        "/matches",
        match_route,
        capability=_MATCH,
        methods=["POST"],
        response_model=IdentityMatchView,
    )
    add_capability_route(
        router,
        "/adoptions",
        adopt_route,
        capability=_ADOPT,
        methods=["POST"],
        response_model=IdentityAdoptionView,
        status_code=status.HTTP_201_CREATED,
    )
