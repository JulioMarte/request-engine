from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from request_engine.modules.delivery.adapters.db.service_session_reader import (
    PostgresServiceSessionReader,
)
from request_engine.modules.delivery.api.live_models import ServiceSessionStatusView
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability


def create_service_session_read_router(
    reader: PostgresServiceSessionReader,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter()

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def read_session(
        service_session_id: UUID,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> ServiceSessionStatusView:
        require_capability(current, "service_session.read")
        item = await reader.get(current.organization_id, service_session_id)
        return ServiceSessionStatusView.from_snapshot(item)

    add_capability_route(
        router,
        "/service-sessions/{service_session_id}",
        read_session,
        capability="service_session.read",
        methods=["GET"],
        response_model=ServiceSessionStatusView,
    )
    return router
