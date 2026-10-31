from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.queue.application.commands.set_service_queue_active import (
    SetServiceQueueActiveCommand,
    SetServiceQueueActiveHandler,
    set_service_queue_active,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=250),
]


class SetServiceQueueActiveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authority_party_id: UUID
    expected_revision: int = Field(gt=0)
    active: bool


class ServiceQueueActivationView(BaseModel):
    queue_id: UUID
    queue_key: str
    display_name: str
    location_id: UUID | None
    offering_id: UUID | None
    active: bool
    revision: int


def create_service_queue_activation_router(
    *,
    handler: SetServiceQueueActiveHandler,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1/queues", tags=["queue-configuration"])

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def set_active(
        queue_id: UUID,
        body: SetServiceQueueActiveBody,
        idempotency_key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> ServiceQueueActivationView:
        require_capability(current, "queue.configure")
        state = await set_service_queue_active(
            handler,
            SetServiceQueueActiveCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                authority_party_id=body.authority_party_id,
                queue_id=queue_id,
                expected_revision=body.expected_revision,
                active=body.active,
                idempotency_key=idempotency_key,
            ),
        )
        return ServiceQueueActivationView(
            queue_id=state.queue_id,
            queue_key=state.queue_key,
            display_name=state.display_name,
            location_id=state.location_id,
            offering_id=state.offering_id,
            active=state.active,
            revision=state.revision,
        )

    add_capability_route(
        router,
        "/{queue_id}:set-active",
        set_active,
        capability="queue.configure",
        methods=["POST"],
        operation_id="queue_service_queue_set_active",
        owner="queue",
        response_model=ServiceQueueActivationView,
    )
    return router
