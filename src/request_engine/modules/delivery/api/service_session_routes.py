from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status

from request_engine.modules.delivery.adapters.db.live_service_operations import PostgresLiveServiceOperations
from request_engine.modules.delivery.adapters.db.service_session_reader import PostgresServiceSessionReader
from request_engine.modules.delivery.api.live_models import (
    CompleteServiceBody,
    PauseServiceBody,
    ResumeServiceBody,
    ServiceSessionView,
    StartServiceBody,
)
from request_engine.modules.delivery.application.service_session_commands import (
    CompleteServiceCommand,
    PauseServiceCommand,
    ResumeServiceCommand,
    StartServiceCommand,
)
from request_engine.modules.delivery.contracts.service_session import InterruptionKind
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability

IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=250)]


def create_service_session_router(
    operations: PostgresLiveServiceOperations,
    reader: PostgresServiceSessionReader,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter()

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def start(
        queue_entry_id: UUID, body: StartServiceBody,
        current: Annotated[ActorContext, Depends(actor)], idempotency_key: IdempotencyKey,
    ) -> ServiceSessionView:
        require_capability(current, "service_session.start")
        result = await operations.start_service(StartServiceCommand(
            organization_id=current.organization_id, principal_id=current.principal_id,
            queue_entry_id=queue_entry_id, resource_id=body.resource_id,
            location_id=body.location_id, expected_queue_revision=body.expected_queue_revision,
            actual_workload_classification_id=body.actual_workload_classification_id,
            idempotency_key=idempotency_key,
        ))
        return ServiceSessionView.from_contract(result)

    async def pause(
        service_session_id: UUID, body: PauseServiceBody,
        current: Annotated[ActorContext, Depends(actor)], idempotency_key: IdempotencyKey,
    ) -> ServiceSessionView:
        require_capability(current, "service_session.pause")
        result = await operations.pause_service(PauseServiceCommand(
            organization_id=current.organization_id, principal_id=current.principal_id,
            service_session_id=service_session_id, expected_revision=body.expected_revision,
            kind=InterruptionKind(body.kind), idempotency_key=idempotency_key,
        ))
        return ServiceSessionView.from_contract(result)

    async def resume(
        service_session_id: UUID, body: ResumeServiceBody,
        current: Annotated[ActorContext, Depends(actor)], idempotency_key: IdempotencyKey,
    ) -> ServiceSessionView:
        require_capability(current, "service_session.resume")
        result = await operations.resume_service(ResumeServiceCommand(
            organization_id=current.organization_id, principal_id=current.principal_id,
            service_session_id=service_session_id, expected_revision=body.expected_revision,
            idempotency_key=idempotency_key,
        ))
        return ServiceSessionView.from_contract(result)

    async def complete(
        service_session_id: UUID, body: CompleteServiceBody,
        current: Annotated[ActorContext, Depends(actor)], idempotency_key: IdempotencyKey,
    ) -> ServiceSessionView:
        require_capability(current, "service_session.complete")
        result = await operations.complete_service(CompleteServiceCommand(
            organization_id=current.organization_id, principal_id=current.principal_id,
            service_session_id=service_session_id, expected_revision=body.expected_revision,
            actual_workload_classification_id=body.actual_workload_classification_id,
            idempotency_key=idempotency_key,
        ))
        return ServiceSessionView.from_contract(result)

    async def read_session(
        service_session_id: UUID, current: Annotated[ActorContext, Depends(actor)]
    ) -> ServiceSessionView:
        require_capability(current, "service_session.read")
        return ServiceSessionView.from_contract(
            await reader.get(current.organization_id, service_session_id)
        )

    add_capability_route(router, "/queue-entries/{queue_entry_id}/service/start", start,
        capability="service_session.start", methods=["POST"], response_model=ServiceSessionView,
        status_code=status.HTTP_201_CREATED)
    add_capability_route(router, "/service-sessions/{service_session_id}/pause", pause,
        capability="service_session.pause", methods=["POST"], response_model=ServiceSessionView)
    add_capability_route(router, "/service-sessions/{service_session_id}/resume", resume,
        capability="service_session.resume", methods=["POST"], response_model=ServiceSessionView)
    add_capability_route(router, "/service-sessions/{service_session_id}/complete", complete,
        capability="service_session.complete", methods=["POST"], response_model=ServiceSessionView)
    add_capability_route(router, "/service-sessions/{service_session_id}", read_session,
        capability="service_session.read", methods=["GET"], response_model=ServiceSessionView)
    return router
