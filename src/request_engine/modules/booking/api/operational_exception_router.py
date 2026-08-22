from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel

from request_engine.modules.booking.application.commands import (
    set_resource_location_schedule_exception as assignment_exception_command,
)
from request_engine.modules.booking.application.commands import (
    set_resource_schedule_exception as resource_exception_command,
)
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=250),
]


class ExceptionBody(BaseModel):
    authority_party_id: UUID
    start_at: datetime
    end_at: datetime
    exception_kind: Literal["available", "unavailable"]
    expected_resource_availability_revision: int
    exception_id: UUID | None = None
    reason: str | None = None
    active: bool = True


class ResourceExceptionBody(BaseModel):
    authority_party_id: UUID
    start_at: datetime
    end_at: datetime
    exception_kind: Literal["available", "unavailable"]
    expected_resource_availability_revision: int
    exception_id: UUID | None = None
    reason: str | None = None


def create_operational_exception_router(
    *,
    assignment_handler: assignment_exception_command.SetResourceLocationScheduleExceptionHandler,
    resource_handler: resource_exception_command.SetResourceScheduleExceptionHandler,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1/operations", tags=["operations"])

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    @router.put("/resource-assignments/{assignment_id}/exceptions")
    async def assignment_exception(
        assignment_id: UUID,
        body: ExceptionBody,
        key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> object:
        command = assignment_exception_command.SetResourceLocationScheduleExceptionCommand(
            organization_id=current.organization_id,
            principal_id=current.principal_id,
            assignment_id=assignment_id,
            idempotency_key=key,
            **body.model_dump(),
        )
        return await assignment_exception_command.set_resource_location_schedule_exception(
            assignment_handler,
            command,
        )

    @router.put("/resources/{resource_id}/exceptions")
    async def resource_exception(
        resource_id: UUID,
        body: ResourceExceptionBody,
        key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> object:
        command = resource_exception_command.SetResourceScheduleExceptionCommand(
            organization_id=current.organization_id,
            principal_id=current.principal_id,
            resource_id=resource_id,
            idempotency_key=key,
            **body.model_dump(),
        )
        return await resource_exception_command.set_resource_schedule_exception(
            resource_handler,
            command,
        )

    return router
