from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict

from request_engine.modules.tenancy.application.commands.bootstrap_operational_authority import (
    BootstrapOperationalAuthorityCommand,
    BootstrapOperationalAuthorityHandler,
    bootstrap_operational_authority,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=250),
]


class BootstrapOperationalAuthorityBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authority_party_id: UUID


def create_bootstrap_authority_router(
    *,
    handler: BootstrapOperationalAuthorityHandler,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1/organization", tags=["organization"])

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def bootstrap(
        body: BootstrapOperationalAuthorityBody,
        idempotency_key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> object:
        require_capability(current, "organization.bootstrap")
        return await bootstrap_operational_authority(
            handler,
            BootstrapOperationalAuthorityCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                authority_party_id=body.authority_party_id,
                idempotency_key=idempotency_key,
            ),
        )

    add_capability_route(
        router,
        "/bootstrap-operational-authority",
        bootstrap,
        capability="organization.bootstrap",
        methods=["POST"],
    )
    return router
