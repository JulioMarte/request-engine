from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from request_engine.modules.queue.api.models import (
    JoinQueueBody,
    LeaveQueueBody,
    QueueEntryView,
    QueueStatusView,
    ServiceQueueView,
)
from request_engine.modules.queue.application.commands.call_next import (
    CallNextCommand,
    CallNextExecutor,
    call_next,
)
from request_engine.modules.queue.application.commands.join_queue import (
    JoinQueueCommand,
    JoinQueueExecutor,
    join_queue,
)
from request_engine.modules.queue.application.commands.leave_queue import (
    LeaveQueueCommand,
    LeaveQueueExecutor,
    leave_queue,
)
from request_engine.modules.queue.application.queries.get_queue_status import (
    QueueStatusReader,
    get_queue_status,
)
from request_engine.modules.queue.application.queries.list_service_queues import (
    ServiceQueueCatalogReader,
    list_service_queues,
)
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, AuthenticationRequired

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=250),
]

SUBJECT_OVERRIDE_PERMISSION = "queue.subject_override"


def create_router(
    *,
    join_executor: JoinQueueExecutor,
    call_next_executor: CallNextExecutor,
    leave_executor: LeaveQueueExecutor,
    reader: QueueStatusReader,
    catalog_reader: ServiceQueueCatalogReader,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1/queues", tags=["queues"])

    async def authenticated_actor(request: Request) -> ActorContext:
        try:
            return await actor_resolver.resolve_actor(request)
        except AuthenticationRequired as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="authentication required",
            ) from exc

    async def queues(
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
    ) -> tuple[ServiceQueueView, ...]:
        _require(actor, "queue.list")
        result = await list_service_queues(
            catalog_reader,
            organization_id=actor.organization_id,
            active_only=True,
        )
        return tuple(ServiceQueueView.from_contract(item) for item in result)

    async def join(
        queue_id: UUID,
        body: JoinQueueBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> QueueEntryView:
        _require(actor, "queue.join")
        entry = await join_queue(
            join_executor,
            JoinQueueCommand(
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                queue_id=queue_id,
                subject_party_id=body.subject_party_id,
                reservation_id=body.reservation_id,
                offering_id=body.offering_id,
                idempotency_key=idempotency_key,
                allow_subject_override=actor.allows(SUBJECT_OVERRIDE_PERMISSION),
            ),
        )
        return QueueEntryView.from_contract(entry)

    async def queue_status(
        queue_id: UUID,
        subject_party_id: UUID,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
    ) -> QueueStatusView:
        _require(actor, "queue.status")
        result = await get_queue_status(
            reader,
            organization_id=actor.organization_id,
            principal_id=actor.principal_id,
            queue_id=queue_id,
            subject_party_id=subject_party_id,
            allow_subject_override=actor.allows(SUBJECT_OVERRIDE_PERMISSION),
        )
        return QueueStatusView.from_contract(result)

    async def leave(
        queue_id: UUID,
        body: LeaveQueueBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> QueueEntryView:
        _require(actor, "queue.leave")
        entry = await leave_queue(
            leave_executor,
            LeaveQueueCommand(
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                queue_id=queue_id,
                subject_party_id=body.subject_party_id,
                reason=body.reason,
                idempotency_key=idempotency_key,
                allow_subject_override=actor.allows(SUBJECT_OVERRIDE_PERMISSION),
            ),
        )
        return QueueEntryView.from_contract(entry)

    async def call_next_entry(
        queue_id: UUID,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> QueueEntryView | None:
        _require(actor, "queue.call_next")
        entry = await call_next(
            call_next_executor,
            CallNextCommand(
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                queue_id=queue_id,
                idempotency_key=idempotency_key,
            ),
        )
        return QueueEntryView.from_contract(entry) if entry is not None else None

    router.add_api_route(
        "",
        queues,
        methods=["GET"],
        response_model=tuple[ServiceQueueView, ...],
    )
    router.add_api_route(
        "/{queue_id}/join",
        join,
        methods=["POST"],
        response_model=QueueEntryView,
        status_code=status.HTTP_201_CREATED,
    )
    router.add_api_route(
        "/{queue_id}/status",
        queue_status,
        methods=["GET"],
        response_model=QueueStatusView,
    )
    router.add_api_route(
        "/{queue_id}/leave",
        leave,
        methods=["POST"],
        response_model=QueueEntryView,
    )
    router.add_api_route(
        "/{queue_id}/call-next",
        call_next_entry,
        methods=["POST"],
        response_model=QueueEntryView | None,
    )
    return router


def _require(actor: ActorContext, capability: str) -> None:
    if not actor.allows(capability):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"capability {capability!r} is required",
        )
