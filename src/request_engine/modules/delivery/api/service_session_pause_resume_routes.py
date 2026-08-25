from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request

from request_engine.modules.delivery.adapters.db.live_service_operations import (
    PostgresLiveServiceOperations,
)
from request_engine.modules.delivery.api.live_models import (
    PauseServiceBody,
    ResumeServiceBody,
    ServiceSessionView,
)
from request_engine.modules.delivery.application.service_session_commands import (
    PauseServiceCommand,
    ResumeServiceCommand,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=250),
]


def create_pause_resume_router(
    operations: PostgresLiveServiceOperations,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter()

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def pause(
        service_session_id: UUID,
        body: PauseServiceBody,
        current: Annotated[ActorContext, Depends(actor)],
        idempotency_key: IdempotencyKey,
    ) -> ServiceSessionView:
        require_capability(current, "service_session.pause")
        item = await operations.pause_service(
            PauseServiceCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                service_session_id=service_session_id,
                expected_revision=body.expected_revision,
                kind=body.kind,
                idempotency_key=idempotency_key,
            )
        )
        return ServiceSessionView.from_contract(item)

    async def resume(
        service_session_id: UUID,
        body: ResumeServiceBody,
        current: Annotated[ActorContext, Depends(actor)],
        idempotency_key: IdempotencyKey,
    ) -> ServiceSessionView:
        require_capability(current, "service_session.resume")
        item = await operations.resume_service(
            ResumeServiceCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                service_session_id=service_session_id,
                expected_revision=body.expected_revision,
                idempotency_key=idempotency_key,
            )
        )
        return ServiceSessionView.from_contract(item)

    add_capability_route(
        router,
        "/service-sessions/{service_session_id}/pause",
        pause,
        capability="service_session.pause",
        methods=["POST"],
        response_model=ServiceSessionView,
    )
    add_capability_route(
        router,
        "/service-sessions/{service_session_id}/resume",
        resume,
        capability="service_session.resume",
        methods=["POST"],
        response_model=ServiceSessionView,
    )
    return router
