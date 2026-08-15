from typing import Protocol
from uuid import UUID

from request_engine.modules.communications.contracts.reminders import ReminderPlan


class ReminderPlanReader(Protocol):
    async def get_reminder_plan(
        self,
        *,
        organization_id: UUID,
        principal_id: UUID,
        reminder_plan_id: UUID,
        allow_subject_override: bool,
    ) -> ReminderPlan | None: ...


async def get_reminder_plan(
    reader: ReminderPlanReader,
    *,
    organization_id: UUID,
    principal_id: UUID,
    reminder_plan_id: UUID,
    allow_subject_override: bool = False,
) -> ReminderPlan | None:
    return await reader.get_reminder_plan(
        organization_id=organization_id,
        principal_id=principal_id,
        reminder_plan_id=reminder_plan_id,
        allow_subject_override=allow_subject_override,
    )
