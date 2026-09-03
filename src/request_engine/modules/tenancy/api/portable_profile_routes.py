"""`identity_exchange.publish` HTTP route attached to the tenant Party surface."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from request_engine.modules.tenancy.api.identity_exchange_dependencies import (
    require_operator_document_witness,
)
from request_engine.modules.tenancy.api.identity_exchange_errors import (
    IdentityExchangeInputInvalid,
)
from request_engine.modules.tenancy.api.identity_exchange_models import (
    PublishPortableProfileBody,
    PublishPortableProfileView,
)
from request_engine.modules.tenancy.api.party_registry_dependencies import (
    IdempotencyKey,
    source_kind,
)
from request_engine.modules.tenancy.application.identity_exchange import (
    PublishPortableProfileCommand,
    PublishPortableProfileHandler,
    publish_portable_profile,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability

_CAPABILITY = "identity_exchange.publish"


def add_portable_profile_routes(
    router: APIRouter,
    *,
    publisher: PublishPortableProfileHandler,
    actor_resolver: ActorResolver,
) -> None:
    async def authenticated_actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def publish_route(
        party_id: UUID,
        body: PublishPortableProfileBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> PublishPortableProfileView:
        require_capability(actor, _CAPABILITY)
        require_operator_document_witness(actor)
        try:
            await publish_portable_profile(
                publisher,
                PublishPortableProfileCommand(
                    organization_id=actor.organization_id,
                    principal_id=actor.principal_id,
                    party_id=party_id,
                    document_kind=body.document_kind,
                    document_authority=body.document_authority,
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
        return PublishPortableProfileView(published=True)

    add_capability_route(
        router,
        "/{party_id}/portable-profile",
        publish_route,
        capability=_CAPABILITY,
        methods=["POST"],
        response_model=PublishPortableProfileView,
        status_code=status.HTTP_201_CREATED,
    )
