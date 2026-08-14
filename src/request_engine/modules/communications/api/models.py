from datetime import time
from uuid import UUID

from pydantic import BaseModel, Field

from request_engine.modules.communications.contracts.reminders import ReminderPlan


class CreateReminderPlanBody(BaseModel):
    subject_party_id: UUID
    purpose: str = Field(min_length=1, max_length=200)
    timezone: str = Field(min_length=1, max_length=100)
    daily_times: tuple[time, ...] = Field(min_length=1, max_length=24)
    max_lateness_minutes: int = Field(default=60, ge=1, le=1440)
    channel_policy: dict[str, object] = Field(default_factory=dict)
    template_key: str = Field(min_length=1, max_length=200)
    template_version: int = Field(ge=1)


class CancelReminderPlanBody(BaseModel):
    expected_revision: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=500)


class ReminderPlanView(BaseModel):
    id: UUID
    subject_party_id: UUID
    purpose: str
    timezone: str
    daily_times: tuple[time, ...]
    max_lateness_minutes: int
    channel_policy: dict[str, object]
    template_key: str
    template_version: int
    status: str
    revision: int

    @classmethod
    def from_contract(cls, plan: ReminderPlan) -> "ReminderPlanView":
        return cls(
            id=plan.id,
            subject_party_id=plan.subject_party_id,
            purpose=plan.purpose,
            timezone=plan.timezone,
            daily_times=plan.schedule.times,
            max_lateness_minutes=plan.schedule.max_lateness_minutes,
            channel_policy=plan.channel_policy,
            template_key=plan.template_key,
            template_version=plan.template_version,
            status=plan.status.value,
            revision=plan.revision,
        )
