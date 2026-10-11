from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import AwareDatetime

from request_engine.modules.delivery.adapters.db.live_service_operations import (
    PostgresLiveServiceOperations,
)
from request_engine.modules.delivery.adapters.db.resource_activity_reader import (
    PostgresResourceActivityReader,
)
from request_engine.modules.delivery.api.live_models import (
    EndResourceActivityBody,
    ResourceActivityView,
    StartResourceActivityBody,
)
from request_engine.modules.delivery.api.resource_activity_pagination import (
    ResourceActivityCursorParams,
    ResourceActivityPageView,
    activity_filter_key,
    decode_activity_cursor,
    encode_activity_cursor,
)
from request_engine.modules.delivery.application.resource_activity_commands import (
    EndResourceActivityCommand,
    StartResourceActivityCommand,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=250),
]


def create_resource_activity_router(
    operations: PostgresLiveServiceOperations,
    reader: PostgresResourceActivityReader,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter()

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def list_activities(
        request: Request,
        resource_id: UUID,
        current: Annotated[ActorContext, Depends(actor)],
        active_only: Annotated[bool, Query()] = True,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        cursor: Annotated[str | None, Query(max_length=2000)] = None,
        started_after: AwareDatetime | None = None,
        started_before: AwareDatetime | None = None,
    ) -> ResourceActivityPageView:
        require_capability(current, "resource_activity.read")
        if set(request.query_params) - {
            "resource_id",
            "active_only",
            "limit",
            "cursor",
            "started_after",
            "started_before",
        }:
            raise HTTPException(status_code=422, detail="unsupported activity filter")
        if (
            started_after is not None
            and started_before is not None
            and (started_after >= started_before)
        ):
            raise HTTPException(status_code=422, detail="activity window must be positive")
        filter_key = activity_filter_key(
            current.organization_id,
            resource_id,
            active_only,
            started_after,
            started_before,
        )
        position = decode_activity_cursor(cursor, filter_key) if cursor else None
        items = await reader.list_for_resource(
            current.organization_id,
            resource_id,
            active_only=active_only,
            limit=limit + 1,
            after_started_at=position.started_at if position else None,
            after_id=position.activity_id if position else None,
            started_after=started_after,
            started_before=started_before,
        )
        page = items[:limit]
        next_cursor = None
        if len(items) > limit:
            next_cursor = encode_activity_cursor(
                ResourceActivityCursorParams(
                    filter_key=filter_key,
                    started_at=page[-1].started_at,
                    activity_id=page[-1].id,
                )
            )
        return ResourceActivityPageView(
            items=[ResourceActivityView.from_contract(item) for item in page],
            next_cursor=next_cursor,
        )

    async def start_activity(
        body: StartResourceActivityBody,
        current: Annotated[ActorContext, Depends(actor)],
        idempotency_key: IdempotencyKey,
    ) -> ResourceActivityView:
        require_capability(current, "resource_activity.start")
        result = await operations.start_resource_activity(
            StartResourceActivityCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                resource_id=body.resource_id,
                location_id=body.location_id,
                kind=body.kind,
                idempotency_key=idempotency_key,
            )
        )
        return ResourceActivityView.from_contract(result)

    async def end_activity(
        resource_activity_id: UUID,
        body: EndResourceActivityBody,
        current: Annotated[ActorContext, Depends(actor)],
        idempotency_key: IdempotencyKey,
    ) -> ResourceActivityView:
        require_capability(current, "resource_activity.end")
        result = await operations.end_resource_activity(
            EndResourceActivityCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                resource_activity_id=resource_activity_id,
                expected_revision=body.expected_revision,
                idempotency_key=idempotency_key,
            )
        )
        return ResourceActivityView.from_contract(result)

    add_capability_route(
        router,
        "/resource-activities",
        list_activities,
        capability="resource_activity.read",
        methods=["GET"],
        response_model=ResourceActivityPageView,
    )
    add_capability_route(
        router,
        "/resource-activities",
        start_activity,
        capability="resource_activity.start",
        methods=["POST"],
        response_model=ResourceActivityView,
        status_code=status.HTTP_201_CREATED,
    )
    add_capability_route(
        router,
        "/resource-activities/{resource_activity_id}/end",
        end_activity,
        capability="resource_activity.end",
        methods=["POST"],
        response_model=ResourceActivityView,
    )
    return router
