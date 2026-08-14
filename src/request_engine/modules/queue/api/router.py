from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status

from request_engine.modules.queue.api.models import (
    JoinQueueBody,
    JoinWaitlistBody,
    LeaveQueueBody,
    LeaveWaitlistBody,
    QueueEntryView,
    QueueStatusView,
    ServiceQueueView,
    WaitlistEntryView,
)
from request_engine.modules.queue.application.authority import WAITLIST_SUBJECT_OVERRIDE_PERMISSION
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
from request_engine.modules.queue.application.commands.join_waitlist import (
    JoinWaitlistCommand,
    JoinWaitlistExecutor,
    join_waitlist,
)
from request_engine.modules.queue.application.commands.leave_queue import (
    LeaveQueueCommand,
    LeaveQueueExecutor,
    leave_queue,
)
from request_engine.modules.queue.application.commands.leave_waitlist import (
    LeaveWaitlistCommand,
    LeaveWaitlistExecutor,
    leave_waitlist,
)
from request_engine.modules.queue.application.errors import WaitlistEntryNotFound
from request_engine.modules.queue.application.queries.get_queue_status import (
    QueueStatusReader,
    get_queue_status,
)
from request_engine.modules.queue.application.queries.get_waitlist_entry import (
    WaitlistEntryReader,
    get_waitlist_entry,
)
from request_engine.modules.queue.application.queries.list_service_queues import (
    ServiceQueueCatalogReader,
    list_service_queues,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability

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
    waitlist_join_executor: JoinWaitlistExecutor,
    waitlist_leave_executor: LeaveWaitlistExecutor,
    waitlist_reader: WaitlistEntryReader,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["queues"])

    async def authenticated_actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def queues(
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
    ) -> tuple[ServiceQueueView, ...]:
        require_capability(actor, "queue.list")
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
        require_capability(actor, "queue.join")
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
        require_capability(actor, "queue.status")
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
        queue_entry_id: UUID,
        body: LeaveQueueBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> QueueEntryView:
        require_capability(actor, "queue.leave")
        entry = await leave_queue(
            leave_executor,
            LeaveQueueCommand(
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                queue_id=queue_id,
                queue_entry_id=queue_entry_id,
                expected_revision=body.expected_revision,
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
        require_capability(actor, "queue.call_next")
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

    async def join_waitlist_entry(
        body: JoinWaitlistBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> WaitlistEntryView:
        require_capability(actor, "waitlist.join")
        entry = await join_waitlist(
            waitlist_join_executor,
            JoinWaitlistCommand(
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                offering_id=body.offering_id,
                subject_party_id=body.subject_party_id,
                location_id=body.location_id,
                preferred_resource_id=body.preferred_resource_id,
                earliest_start=body.earliest_start,
                latest_start=body.latest_start,
                idempotency_key=idempotency_key,
                allow_subject_override=actor.allows(WAITLIST_SUBJECT_OVERRIDE_PERMISSION),
            ),
        )
        return WaitlistEntryView.from_contract(entry)

    async def waitlist_entry_status(
        waitlist_entry_id: UUID,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
    ) -> WaitlistEntryView:
        require_capability(actor, "waitlist.read")
        entry = await get_waitlist_entry(
            waitlist_reader,
            organization_id=actor.organization_id,
            principal_id=actor.principal_id,
            waitlist_entry_id=waitlist_entry_id,
            allow_subject_override=actor.allows(WAITLIST_SUBJECT_OVERRIDE_PERMISSION),
        )
        if entry is None:
            raise WaitlistEntryNotFound(waitlist_entry_id)
        return WaitlistEntryView.from_contract(entry)

    async def leave_waitlist_entry(
        waitlist_entry_id: UUID,
        body: LeaveWaitlistBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> WaitlistEntryView:
        require_capability(actor, "waitlist.leave")
        entry = await leave_waitlist(
            waitlist_leave_executor,
            LeaveWaitlistCommand(
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                waitlist_entry_id=waitlist_entry_id,
                expected_revision=body.expected_revision,
                reason=body.reason,
                idempotency_key=idempotency_key,
                allow_subject_override=actor.allows(WAITLIST_SUBJECT_OVERRIDE_PERMISSION),
            ),
        )
        return WaitlistEntryView.from_contract(entry)

    add_capability_route(
        router,
        "/queues",
        queues,
        capability="queue.list",
        methods=["GET"],
        response_model=tuple[ServiceQueueView, ...],
    )
    add_capability_route(
        router,
        "/queues/{queue_id}/join",
        join,
        capability="queue.join",
        methods=["POST"],
        response_model=QueueEntryView,
        status_code=status.HTTP_201_CREATED,
    )
    add_capability_route(
        router,
        "/queues/{queue_id}/status",
        queue_status,
        capability="queue.status",
        methods=["GET"],
        response_model=QueueStatusView,
    )
    add_capability_route(
        router,
        "/queues/{queue_id}/entries/{queue_entry_id}/leave",
        leave,
        capability="queue.leave",
        methods=["POST"],
        response_model=QueueEntryView,
    )
    add_capability_route(
        router,
        "/queues/{queue_id}/call-next",
        call_next_entry,
        capability="queue.call_next",
        methods=["POST"],
        response_model=QueueEntryView | None,
    )
    add_capability_route(
        router,
        "/waitlist",
        join_waitlist_entry,
        capability="waitlist.join",
        methods=["POST"],
        response_model=WaitlistEntryView,
        status_code=status.HTTP_201_CREATED,
    )
    add_capability_route(
        router,
        "/waitlist/{waitlist_entry_id}",
        waitlist_entry_status,
        capability="waitlist.read",
        methods=["GET"],
        response_model=WaitlistEntryView,
    )
    add_capability_route(
        router,
        "/waitlist/{waitlist_entry_id}/leave",
        leave_waitlist_entry,
        capability="waitlist.leave",
        methods=["POST"],
        response_model=WaitlistEntryView,
    )
    return router
