from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status
from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.queue.application.commands.create_service_queue import (
    CreateServiceQueueCommand,
    CreateServiceQueueHandler,
    create_service_queue,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=250),
]


class CreateServiceQueueBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authority_party_id: UUID
    location_id: UUID
    offering_id: UUID | None = None
    queue_key: str = Field(min_length=1, max_length=160)
    display_name: str = Field(min_length=1, max_length=200)


def create_service_queue_bootstrap_router(
    *,
    handler: CreateServiceQueueHandler,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1/queues", tags=["queue-configuration"])

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def create(
        body: CreateServiceQueueBody,
        idempotency_key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> object:
        require_capability(current, "queue.configure")
        return await create_service_queue(
            handler,
            CreateServiceQueueCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                authority_party_id=body.authority_party_id,
                location_id=body.location_id,
                offering_id=body.offering_id,
                queue_key=body.queue_key,
                display_name=body.display_name,
                idempotency_key=idempotency_key,
            ),
        )

    add_capability_route(
        router,
        "",
        create,
        capability="queue.configure",
        methods=["POST"],
        status_code=status.HTTP_201_CREATED,
    )
    return router
