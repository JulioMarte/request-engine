from typing import Annotated, Literal, Self
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from request_engine.modules.booking.api.configuration_models import (
    AssignmentScheduleExceptionView,
    ResourceScheduleExceptionView,
)
from request_engine.modules.booking.application.commands import (
    set_resource_location_schedule_exception as assignment_exception_command,
)
from request_engine.modules.booking.application.commands import (
    set_resource_schedule_exception as resource_exception_command,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=250),
]


class ExceptionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authority_party_id: UUID
    start_at: AwareDatetime
    end_at: AwareDatetime
    exception_kind: Literal["available", "unavailable"]
    expected_resource_availability_revision: int = Field(gt=0)
    exception_id: UUID | None = None
    reason: str | None = Field(default=None, pattern=r"\S")
    active: bool = True

    @model_validator(mode="after")
    def interval(self) -> Self:
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at")
        return self


class ResourceExceptionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authority_party_id: UUID
    start_at: AwareDatetime
    end_at: AwareDatetime
    exception_kind: Literal["available", "unavailable"]
    expected_resource_availability_revision: int = Field(gt=0)
    exception_id: UUID | None = None
    reason: str | None = Field(default=None, pattern=r"\S")

    @model_validator(mode="after")
    def interval(self) -> Self:
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at")
        return self


def create_operational_exception_router(
    *,
    assignment_handler: assignment_exception_command.SetResourceLocationScheduleExceptionHandler,
    resource_handler: resource_exception_command.SetResourceScheduleExceptionHandler,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1/operations", tags=["operations"])

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def assignment_exception(
        assignment_id: UUID,
        body: ExceptionBody,
        key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> AssignmentScheduleExceptionView:
        command = assignment_exception_command.SetResourceLocationScheduleExceptionCommand(
            organization_id=current.organization_id,
            principal_id=current.principal_id,
            assignment_id=assignment_id,
            idempotency_key=key,
            **body.model_dump(),
        )
        result = await assignment_exception_command.set_resource_location_schedule_exception(
            assignment_handler,
            command,
        )
        return AssignmentScheduleExceptionView.model_validate(result)

    async def resource_exception(
        resource_id: UUID,
        body: ResourceExceptionBody,
        key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> ResourceScheduleExceptionView:
        command = resource_exception_command.SetResourceScheduleExceptionCommand(
            organization_id=current.organization_id,
            principal_id=current.principal_id,
            resource_id=resource_id,
            idempotency_key=key,
            **body.model_dump(),
        )
        result = await resource_exception_command.set_resource_schedule_exception(
            resource_handler,
            command,
        )
        return ResourceScheduleExceptionView.model_validate(result)

    add_capability_route(
        router,
        "/resource-assignments/{assignment_id}/exceptions",
        assignment_exception,
        methods=["PUT"],
        capability="booking.manage_supply",
        operation_id="booking_resource_assignment_exception_set",
        owner="booking",
        response_model=AssignmentScheduleExceptionView,
    )
    add_capability_route(
        router,
        "/resources/{resource_id}/exceptions",
        resource_exception,
        methods=["PUT"],
        capability="booking.manage_supply",
        operation_id="booking_resource_exception_set",
        owner="booking",
        response_model=ResourceScheduleExceptionView,
    )
    return router
