from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status

from request_engine.modules.communications.api.models import (
    CancelReminderPlanBody,
    CreateReminderPlanBody,
    ReminderPlanView,
)
from request_engine.modules.communications.application.commands.cancel_reminder_plan import (
    CancelReminderPlanCommand,
    CancelReminderPlanHandler,
    cancel_reminder_plan,
)
from request_engine.modules.communications.application.commands.create_reminder_plan import (
    CreateReminderPlanCommand,
    CreateReminderPlanHandler,
    create_reminder_plan,
)
from request_engine.modules.communications.application.errors import ReminderPlanNotFound
from request_engine.modules.communications.application.queries.get_reminder_plan import (
    ReminderPlanReader,
    get_reminder_plan,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=250),
]

REMINDER_SUBJECT_OVERRIDE = "reminders.subject_override"


class ReminderPlanCommands(CreateReminderPlanHandler, CancelReminderPlanHandler, Protocol):
    """Combined command surface required by the HTTP adapter."""


def create_router(
    *,
    commands: ReminderPlanCommands,
    reader: ReminderPlanReader,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1/reminders", tags=["reminders"])

    async def authenticated_actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def create_plan(
        body: CreateReminderPlanBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> ReminderPlanView:
        require_capability(actor, "reminders.create_plan")
        plan = await create_reminder_plan(
            commands,
            CreateReminderPlanCommand(
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                subject_party_id=body.subject_party_id,
                purpose=body.purpose,
                timezone=body.timezone,
                daily_times=body.daily_times,
                max_lateness_minutes=body.max_lateness_minutes,
                channel_policy=body.channel_policy,
                template_key=body.template_key,
                template_version=body.template_version,
                idempotency_key=idempotency_key,
                allow_subject_override=actor.allows(REMINDER_SUBJECT_OVERRIDE),
            ),
        )
        return ReminderPlanView.from_contract(plan)

    async def read_plan(
        reminder_plan_id: UUID,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
    ) -> ReminderPlanView:
        require_capability(actor, "reminders.read")
        plan = await get_reminder_plan(
            reader,
            organization_id=actor.organization_id,
            principal_id=actor.principal_id,
            reminder_plan_id=reminder_plan_id,
            allow_subject_override=actor.allows(REMINDER_SUBJECT_OVERRIDE),
        )
        if plan is None:
            raise ReminderPlanNotFound(reminder_plan_id)
        return ReminderPlanView.from_contract(plan)

    async def cancel_plan(
        reminder_plan_id: UUID,
        body: CancelReminderPlanBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> ReminderPlanView:
        require_capability(actor, "reminders.cancel_plan")
        plan = await cancel_reminder_plan(
            commands,
            CancelReminderPlanCommand(
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                reminder_plan_id=reminder_plan_id,
                expected_revision=body.expected_revision,
                reason=body.reason,
                idempotency_key=idempotency_key,
                allow_subject_override=actor.allows(REMINDER_SUBJECT_OVERRIDE),
            ),
        )
        return ReminderPlanView.from_contract(plan)

    add_capability_route(
        router,
        "",
        create_plan,
        capability="reminders.create_plan",
        methods=["POST"],
        response_model=ReminderPlanView,
        status_code=status.HTTP_201_CREATED,
    )
    add_capability_route(
        router,
        "/{reminder_plan_id}",
        read_plan,
        capability="reminders.read",
        methods=["GET"],
        response_model=ReminderPlanView,
    )
    add_capability_route(
        router,
        "/{reminder_plan_id}/cancel",
        cancel_plan,
        capability="reminders.cancel_plan",
        methods=["POST"],
        response_model=ReminderPlanView,
    )
    return router
