from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.modules.communications.contracts.reminders import ReminderPlan


@dataclass(frozen=True, slots=True)
class CancelReminderPlanCommand:
    organization_id: UUID
    principal_id: UUID
    reminder_plan_id: UUID
    expected_revision: int
    idempotency_key: str
    reason: str | None = None
    allow_subject_override: bool = False


class CancelReminderPlanHandler(Protocol):
    async def cancel_reminder_plan(self, command: CancelReminderPlanCommand) -> ReminderPlan: ...


async def cancel_reminder_plan(
    handler: CancelReminderPlanHandler,
    command: CancelReminderPlanCommand,
) -> ReminderPlan:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if command.expected_revision <= 0:
        raise ValueError("expected_revision must be positive")
    return await handler.cancel_reminder_plan(command)
