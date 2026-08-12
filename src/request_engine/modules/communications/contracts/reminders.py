from dataclasses import dataclass
from datetime import time
from enum import StrEnum
from uuid import UUID


class ReminderPlanStatus(StrEnum):
    ACTIVE = "active"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class DailyReminderSchedule:
    times: tuple[time, ...]


@dataclass(frozen=True, slots=True)
class ReminderPlan:
    id: UUID
    subject_party_id: UUID
    purpose: str
    timezone: str
    schedule: DailyReminderSchedule
    channel_policy: dict[str, object]
    template_key: str
    template_version: int
    status: ReminderPlanStatus
    revision: int
