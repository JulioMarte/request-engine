from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.communications.adapters.db.reminder_commands import (
    REMINDER_ACTION_TYPE,
    REMINDER_ACTION_VERSION,
    database_now,
    lock_reminder_plan,
    reminder_plan_from_row,
    schedule_reminder_occurrence,
)
from request_engine.modules.communications.adapters.db.task_store import (
    CommunicationTaskIntent,
    insert_or_reuse_communication_task,
)
from request_engine.modules.communications.application.errors import UnsupportedScheduledAction
from request_engine.modules.communications.contracts.reminders import ReminderPlan
from request_engine.modules.communications.domain.daily_schedule import next_daily_occurrence
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.outbox.postgres import append_outbox
from request_engine.platform.scheduling.postgres import ScheduledActionLease
from request_engine.platform.scheduling.store import schedule_action


@dataclass(frozen=True, slots=True)
class ReminderOccurrenceResult:
    reminder_plan_id: UUID
    occurrence_at: datetime
    communication_task_id: UUID | None
    next_occurrence_at: datetime | None
    skipped_reason: str | None


class PostgresReminderOccurrenceCommands:
    """Materialize one leased ReminderPlan occurrence without provider I/O."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def materialize(self, lease: ScheduledActionLease) -> ReminderOccurrenceResult:
        reminder_plan_id, occurrence_at = _validate_lease(lease)

        async with tenant_transaction(self._session_factory, lease.organization_id) as session:
            row = await lock_reminder_plan(
                session,
                organization_id=lease.organization_id,
                reminder_plan_id=reminder_plan_id,
            )
            plan = reminder_plan_from_row(row)
            db_now = await database_now(session)
            if occurrence_at > db_now:
                raise ValueError("reminder occurrence was claimed before execute_at")

            if plan.status.value != "active":
                return ReminderOccurrenceResult(
                    reminder_plan_id=plan.id,
                    occurrence_at=occurrence_at,
                    communication_task_id=None,
                    next_occurrence_at=None,
                    skipped_reason="plan_inactive",
                )

            next_occurrence = await _ensure_next_occurrence(
                session,
                organization_id=lease.organization_id,
                plan=plan,
                current_occurrence_at=occurrence_at,
                db_now=db_now,
            )

            recipient_active = cast(
                bool,
                (
                    await session.execute(
                        text(
                            """
                            SELECT active
                            FROM request_engine.parties
                            WHERE organization_id = :organization_id
                              AND id = :subject_party_id
                            """
                        ),
                        {
                            "organization_id": lease.organization_id,
                            "subject_party_id": plan.subject_party_id,
                        },
                    )
                ).scalar_one(),
            )
            if not recipient_active:
                return ReminderOccurrenceResult(
                    reminder_plan_id=plan.id,
                    occurrence_at=occurrence_at,
                    communication_task_id=None,
                    next_occurrence_at=next_occurrence,
                    skipped_reason="recipient_inactive",
                )

            expires_at = occurrence_at + timedelta(minutes=plan.schedule.max_lateness_minutes)
            if db_now >= expires_at:
                return ReminderOccurrenceResult(
                    reminder_plan_id=plan.id,
                    occurrence_at=occurrence_at,
                    communication_task_id=None,
                    next_occurrence_at=next_occurrence,
                    skipped_reason="occurrence_too_late",
                )

            task, created = await insert_or_reuse_communication_task(
                session,
                CommunicationTaskIntent(
                    organization_id=lease.organization_id,
                    recipient_party_id=plan.subject_party_id,
                    contact_point_id=None,
                    purpose=plan.purpose,
                    source_kind="ReminderPlan",
                    source_id=plan.id,
                    channel_policy=plan.channel_policy,
                    template_key=plan.template_key,
                    template_version=plan.template_version,
                    render_context={
                        "reminder_plan_id": str(plan.id),
                        "occurrence_at": occurrence_at.isoformat(),
                    },
                    dedupe_key=(f"reminder-task:{plan.id}:{occurrence_at.isoformat()}:v1"),
                    not_before=occurrence_at,
                    expires_at=expires_at,
                ),
            )
            if created:
                await schedule_action(
                    session,
                    organization_id=lease.organization_id,
                    owner_module="communications",
                    action_type="dispatch_task",
                    action_version=1,
                    subject_kind="CommunicationTask",
                    subject_id=task.id,
                    dedupe_key=f"communications:dispatch:{task.id}:v1",
                    execute_at=occurrence_at,
                    payload={"communication_task_id": str(task.id)},
                    max_attempts=8,
                )
                await append_outbox(
                    session,
                    organization_id=lease.organization_id,
                    event_type="communication.task_created.v1",
                    aggregate_kind="CommunicationTask",
                    aggregate_id=task.id,
                    payload={
                        "communication_task_id": str(task.id),
                        "recipient_party_id": str(task.recipient_party_id),
                        "purpose": task.purpose,
                        "source_kind": "ReminderPlan",
                        "source_id": str(plan.id),
                        "occurrence_at": occurrence_at.isoformat(),
                    },
                )
            return ReminderOccurrenceResult(
                reminder_plan_id=plan.id,
                occurrence_at=occurrence_at,
                communication_task_id=task.id,
                next_occurrence_at=next_occurrence,
                skipped_reason=None,
            )


async def _ensure_next_occurrence(
    session: AsyncSession,
    *,
    organization_id: UUID,
    plan: ReminderPlan,
    current_occurrence_at: datetime,
    db_now: datetime,
) -> datetime:
    existing = (
        await session.execute(
            text(
                """
                SELECT execute_at
                FROM request_engine.scheduled_actions
                WHERE organization_id = :organization_id
                  AND owner_module = 'communications'
                  AND action_type = :action_type
                  AND subject_kind = 'ReminderPlan'
                  AND subject_id = :reminder_plan_id
                  AND execute_at > :current_occurrence_at
                ORDER BY execute_at, id
                LIMIT 1
                """
            ),
            {
                "organization_id": organization_id,
                "action_type": REMINDER_ACTION_TYPE,
                "reminder_plan_id": plan.id,
                "current_occurrence_at": current_occurrence_at,
            },
        )
    ).scalar_one_or_none()
    if existing is not None:
        return cast(datetime, existing)

    next_occurrence = next_daily_occurrence(
        after=db_now,
        timezone=plan.timezone,
        times=plan.schedule.times,
    )
    await schedule_reminder_occurrence(
        session,
        organization_id=organization_id,
        reminder_plan_id=plan.id,
        occurrence_at=next_occurrence,
    )
    return next_occurrence


def _validate_lease(lease: ScheduledActionLease) -> tuple[UUID, datetime]:
    if (
        lease.owner_module != "communications"
        or lease.action_type != REMINDER_ACTION_TYPE
        or lease.action_version != REMINDER_ACTION_VERSION
        or lease.subject_kind != "ReminderPlan"
        or lease.subject_id is None
    ):
        raise UnsupportedScheduledAction(
            lease.owner_module,
            lease.action_type,
            lease.action_version,
        )

    payload_plan_id = lease.payload.get("reminder_plan_id")
    payload_occurrence = lease.payload.get("occurrence_at")
    if not isinstance(payload_plan_id, str) or not isinstance(payload_occurrence, str):
        raise ValueError("reminder action payload is malformed")
    reminder_plan_id = UUID(payload_plan_id)
    if reminder_plan_id != lease.subject_id:
        raise ValueError("reminder action subject does not match payload")
    occurrence_at = datetime.fromisoformat(payload_occurrence)
    if occurrence_at.tzinfo is None or occurrence_at.utcoffset() is None:
        raise ValueError("reminder occurrence_at must be timezone-aware")
    return reminder_plan_id, occurrence_at
