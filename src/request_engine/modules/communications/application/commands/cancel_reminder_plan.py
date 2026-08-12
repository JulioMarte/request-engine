from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.modules.communications.contracts.reminders import ReminderPlan


@dataclass(frozen=True, slots=True)
class CancelReminderPlanCommand:
    organization_id: UUID
    principal_id: UUID
    reminder_plan_id: UUID
    idempotency_key: str
    reason: str | None = None


class CancelReminderPlanHandler(Protocol):
    async def cancel_reminder_plan(self, command: CancelReminderPlanCommand) -> ReminderPlan: ...


async def cancel_reminder_plan(
    handler: CancelReminderPlanHandler,
    command: CancelReminderPlanCommand,
) -> ReminderPlan:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    return await handler.cancel_reminder_plan(command)
