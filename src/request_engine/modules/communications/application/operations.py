from dataclasses import dataclass
from datetime import datetime, time
from uuid import UUID

from request_engine.modules.communications.application.commands.cancel_reminder_plan import (
    CancelReminderPlanCommand,
    CancelReminderPlanHandler,
    cancel_reminder_plan,
)
from request_engine.modules.communications.application.commands.create_communication_task import (
    CreateCommunicationTaskCommand,
    CreateCommunicationTaskHandler,
    create_communication_task,
)
from request_engine.modules.communications.application.commands.create_reminder_plan import (
    CreateReminderPlanCommand,
    CreateReminderPlanHandler,
    create_reminder_plan,
)
from request_engine.modules.communications.application.subject_policy import (
    REMINDERS_SUBJECT_OVERRIDE,
)
from request_engine.modules.communications.contracts.reminders import ReminderPlan
from request_engine.modules.communications.contracts.tasks import CommunicationTask
from request_engine.platform.security.authorization import require_capability
from request_engine.platform.security.context import ActorContext


@dataclass(frozen=True, slots=True)
class SendCommunicationInput:
    recipient_party_id: UUID
    purpose: str
    template_key: str
    template_version: int
    channel_policy: dict[str, object]
    render_context: dict[str, object]
    contact_point_id: UUID | None = None
    source_kind: str | None = None
    source_id: UUID | None = None
    dedupe_key: str | None = None
    not_before: datetime | None = None
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class CreateReminderPlanInput:
    subject_party_id: UUID
    purpose: str
    timezone: str
    daily_times: tuple[time, ...]
    channel_policy: dict[str, object]
    template_key: str
    template_version: int
    max_lateness_minutes: int = 60


@dataclass(frozen=True, slots=True)
class CancelReminderPlanInput:
    reminder_plan_id: UUID
    expected_revision: int
    reason: str | None = None


class CommunicationsOperations:
    """Transport-neutral semantic boundary for transactional communications."""

    def __init__(
        self,
        *,
        communication_handler: CreateCommunicationTaskHandler,
        reminder_handler: CreateReminderPlanHandler | CancelReminderPlanHandler,
    ) -> None:
        self._communication_handler = communication_handler
        self._reminder_handler = reminder_handler

    async def send_transactional(
        self,
        actor: ActorContext,
        input_: SendCommunicationInput,
        *,
        idempotency_key: str,
    ) -> CommunicationTask:
        require_capability(actor, "communications.send")
        return await create_communication_task(
            self._communication_handler,
            CreateCommunicationTaskCommand(
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                recipient_party_id=input_.recipient_party_id,
                purpose=input_.purpose,
                template_key=input_.template_key,
                template_version=input_.template_version,
                channel_policy=input_.channel_policy,
                render_context=input_.render_context,
                idempotency_key=idempotency_key,
                contact_point_id=input_.contact_point_id,
                source_kind=input_.source_kind,
                source_id=input_.source_id,
                dedupe_key=input_.dedupe_key,
                not_before=input_.not_before,
                expires_at=input_.expires_at,
            ),
        )

    async def create_reminder_plan(
        self,
        actor: ActorContext,
        input_: CreateReminderPlanInput,
        *,
        idempotency_key: str,
    ) -> ReminderPlan:
        require_capability(actor, "reminders.create")
        return await create_reminder_plan(
            self._reminder_handler,
            CreateReminderPlanCommand(
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                subject_party_id=input_.subject_party_id,
                purpose=input_.purpose,
                timezone=input_.timezone,
                daily_times=input_.daily_times,
                channel_policy=input_.channel_policy,
                template_key=input_.template_key,
                template_version=input_.template_version,
                idempotency_key=idempotency_key,
                max_lateness_minutes=input_.max_lateness_minutes,
                allow_subject_override=actor.allows(REMINDERS_SUBJECT_OVERRIDE),
            ),
        )

    async def cancel_reminder_plan(
        self,
        actor: ActorContext,
        input_: CancelReminderPlanInput,
        *,
        idempotency_key: str,
    ) -> ReminderPlan:
        require_capability(actor, "reminders.cancel")
        return await cancel_reminder_plan(
            self._reminder_handler,
            CancelReminderPlanCommand(
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                reminder_plan_id=input_.reminder_plan_id,
                idempotency_key=idempotency_key,
                expected_revision=input_.expected_revision,
                reason=input_.reason,
                allow_subject_override=actor.allows(REMINDERS_SUBJECT_OVERRIDE),
            ),
        )
