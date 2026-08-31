from dataclasses import dataclass
from datetime import time
from typing import Protocol
from uuid import UUID

from request_engine.modules.communications.contracts.reminders import ReminderPlan
from request_engine.modules.communications.domain.delivery_policy import parse_delivery_policy


@dataclass(frozen=True, slots=True)
class CreateReminderPlanCommand:
    organization_id: UUID
    principal_id: UUID
    subject_party_id: UUID
    purpose: str
    timezone: str
    daily_times: tuple[time, ...]
    channel_policy: dict[str, object]
    template_key: str
    template_version: int
    idempotency_key: str
    max_lateness_minutes: int = 60
    allow_subject_override: bool = False


class CreateReminderPlanHandler(Protocol):
    async def create_reminder_plan(self, command: CreateReminderPlanCommand) -> ReminderPlan: ...


async def create_reminder_plan(
    handler: CreateReminderPlanHandler,
    command: CreateReminderPlanCommand,
) -> ReminderPlan:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if not command.purpose:
        raise ValueError("purpose is required")
    if not command.template_key:
        raise ValueError("template_key is required")
    if command.template_version <= 0:
        raise ValueError("template_version must be positive")
    if command.max_lateness_minutes <= 0 or command.max_lateness_minutes > 1440:
        raise ValueError("max_lateness_minutes must be between 1 and 1440")
    parse_delivery_policy(command.channel_policy)
    return await handler.create_reminder_plan(command)
