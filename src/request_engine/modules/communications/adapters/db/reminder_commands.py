import json
from datetime import datetime, time
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.communications.adapters.db.reminder_authority import (
    require_reminder_subject_authority,
)
from request_engine.modules.communications.adapters.db.task_store import (
    validate_recipient_and_contact_point,
)
from request_engine.modules.communications.application.commands.cancel_reminder_plan import (
    CancelReminderPlanCommand,
)
from request_engine.modules.communications.application.commands.create_reminder_plan import (
    CreateReminderPlanCommand,
)
from request_engine.modules.communications.application.errors import (
    ReminderPlanNotActive,
    ReminderPlanNotFound,
    ReminderPlanRevisionConflict,
)
from request_engine.modules.communications.contracts.reminders import (
    DailyReminderSchedule,
    ReminderPlan,
    ReminderPlanStatus,
)
from request_engine.modules.communications.domain.daily_schedule import (
    next_daily_occurrence,
    normalize_daily_times,
)
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)
from request_engine.platform.outbox.postgres import append_outbox
from request_engine.platform.scheduling.store import schedule_action

REMINDER_ACTION_TYPE = "materialize_reminder_occurrence"
REMINDER_ACTION_VERSION = 1
REMINDER_SCHEDULE_TYPE = "daily_times"
REMINDER_SCHEDULE_VERSION = 1


class PostgresReminderCommands:
    """Durable ReminderPlan lifecycle commands with transactional Party authority."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def create_reminder_plan(self, command: CreateReminderPlanCommand) -> ReminderPlan:
        daily_times = normalize_daily_times(command.daily_times)
        fingerprint = command_fingerprint(
            "reminders.create_plan",
            {
                "subject_party_id": command.subject_party_id,
                "purpose": command.purpose,
                "timezone": command.timezone,
                "daily_times": [value.isoformat() for value in daily_times],
                "max_lateness_minutes": command.max_lateness_minutes,
                "channel_policy": command.channel_policy,
                "template_key": command.template_key,
                "template_version": command.template_version,
            },
        )

        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability="reminders.create_plan",
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return reminder_plan_from_json(cast(dict[str, object], replay["reminder_plan"]))

            authority = await require_reminder_subject_authority(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                subject_party_id=command.subject_party_id,
                allow_operator_override=command.allow_subject_override,
            )
            await validate_recipient_and_contact_point(
                session,
                organization_id=command.organization_id,
                recipient_party_id=command.subject_party_id,
                contact_point_id=None,
            )
            db_now = await database_now(session)
            first_occurrence = next_daily_occurrence(
                after=db_now,
                timezone=command.timezone,
                times=daily_times,
            )
            schedule_spec: dict[str, object] = {
                "type": REMINDER_SCHEDULE_TYPE,
                "version": REMINDER_SCHEDULE_VERSION,
                "times": [value.isoformat() for value in daily_times],
                "max_lateness_minutes": command.max_lateness_minutes,
            }
            row = (
                (
                    await session.execute(
                        text(
                            """
                            INSERT INTO request_engine.reminder_plans (
                                organization_id,
                                subject_party_id,
                                purpose,
                                timezone,
                                schedule_spec,
                                channel_policy,
                                template_key,
                                template_version
                            ) VALUES (
                                :organization_id,
                                :subject_party_id,
                                :purpose,
                                :timezone,
                                CAST(:schedule_spec AS jsonb),
                                CAST(:channel_policy AS jsonb),
                                :template_key,
                                :template_version
                            )
                            RETURNING *
                            """
                        ),
                        {
                            "organization_id": command.organization_id,
                            "subject_party_id": command.subject_party_id,
                            "purpose": command.purpose,
                            "timezone": command.timezone,
                            "schedule_spec": _json(schedule_spec),
                            "channel_policy": _json(command.channel_policy),
                            "template_key": command.template_key,
                            "template_version": command.template_version,
                        },
                    )
                )
                .mappings()
                .one()
            )
            plan = reminder_plan_from_row(row)
            await schedule_reminder_occurrence(
                session,
                organization_id=command.organization_id,
                reminder_plan_id=plan.id,
                plan_revision=plan.revision,
                occurrence_at=first_occurrence,
            )
            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name="reminders.create_plan",
                aggregate_kind="ReminderPlan",
                aggregate_id=plan.id,
                idempotency_id=idempotency_id,
                details={
                    "purpose": plan.purpose,
                    "timezone": plan.timezone,
                    "first_occurrence_at": first_occurrence.isoformat(),
                    "authority": authority.audit_details(),
                },
            )
            await append_outbox(
                session,
                organization_id=command.organization_id,
                event_type="reminder_plan.created.v1",
                aggregate_kind="ReminderPlan",
                aggregate_id=plan.id,
                payload={
                    "reminder_plan_id": str(plan.id),
                    "subject_party_id": str(plan.subject_party_id),
                    "purpose": plan.purpose,
                    "first_occurrence_at": first_occurrence.isoformat(),
                },
            )
            await complete_idempotency(
                session,
                idempotency_id,
                {"reminder_plan": reminder_plan_to_json(plan)},
            )
            return plan

    async def cancel_reminder_plan(self, command: CancelReminderPlanCommand) -> ReminderPlan:
        fingerprint = command_fingerprint(
            "reminders.cancel_plan",
            {
                "reminder_plan_id": command.reminder_plan_id,
                "expected_revision": command.expected_revision,
                "reason": command.reason,
            },
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability="reminders.cancel_plan",
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return reminder_plan_from_json(cast(dict[str, object], replay["reminder_plan"]))

            row = await lock_reminder_plan(
                session,
                organization_id=command.organization_id,
                reminder_plan_id=command.reminder_plan_id,
            )
            subject_party_id = cast(UUID, row["subject_party_id"])
            authority = await require_reminder_subject_authority(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                subject_party_id=subject_party_id,
                allow_operator_override=command.allow_subject_override,
            )
            actual_revision = cast(int, row["revision"])
            if actual_revision != command.expected_revision:
                raise ReminderPlanRevisionConflict(
                    command.reminder_plan_id,
                    command.expected_revision,
                    actual_revision,
                )

            plan_status = ReminderPlanStatus(cast(str, row["status"]))
            changed = False
            if plan_status is ReminderPlanStatus.ACTIVE:
                row = (
                    (
                        await session.execute(
                            text(
                                """
                                UPDATE request_engine.reminder_plans
                                SET status = 'cancelled',
                                    revision = revision + 1,
                                    updated_at = clock_timestamp()
                                WHERE organization_id = :organization_id
                                  AND id = :reminder_plan_id
                                  AND revision = :expected_revision
                                RETURNING *
                                """
                            ),
                            {
                                "organization_id": command.organization_id,
                                "reminder_plan_id": command.reminder_plan_id,
                                "expected_revision": command.expected_revision,
                            },
                        )
                    )
                    .mappings()
                    .one()
                )
                changed = True
                await session.execute(
                    text(
                        """
                        UPDATE request_engine.scheduled_actions
                        SET status = 'cancelled',
                            updated_at = clock_timestamp()
                        WHERE organization_id = :organization_id
                          AND owner_module = 'communications'
                          AND action_type = :action_type
                          AND subject_kind = 'ReminderPlan'
                          AND subject_id = :reminder_plan_id
                          AND status = 'pending'
                        """
                    ),
                    {
                        "organization_id": command.organization_id,
                        "action_type": REMINDER_ACTION_TYPE,
                        "reminder_plan_id": command.reminder_plan_id,
                    },
                )
                await _cancel_pending_reminder_communications(
                    session,
                    organization_id=command.organization_id,
                    reminder_plan_id=command.reminder_plan_id,
                )
            elif plan_status is ReminderPlanStatus.COMPLETED:
                raise ReminderPlanNotActive(command.reminder_plan_id, plan_status.value)

            plan = reminder_plan_from_row(row)
            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name="reminders.cancel_plan",
                aggregate_kind="ReminderPlan",
                aggregate_id=plan.id,
                idempotency_id=idempotency_id,
                details={
                    "reason": command.reason,
                    "already_cancelled": not changed,
                    "authority": authority.audit_details(),
                },
            )
            if changed:
                await append_outbox(
                    session,
                    organization_id=command.organization_id,
                    event_type="reminder_plan.cancelled.v1",
                    aggregate_kind="ReminderPlan",
                    aggregate_id=plan.id,
                    payload={
                        "reminder_plan_id": str(plan.id),
                        "reason": command.reason,
                    },
                )
            await complete_idempotency(
                session,
                idempotency_id,
                {"reminder_plan": reminder_plan_to_json(plan)},
            )
            return plan


async def _cancel_pending_reminder_communications(
    session: AsyncSession,
    *,
    organization_id: UUID,
    reminder_plan_id: UUID,
) -> None:
    task_rows = (
        await session.execute(
            text(
                """
                SELECT id
                FROM request_engine.communication_tasks
                WHERE organization_id = :organization_id
                  AND source_kind = 'ReminderPlan'
                  AND source_id = :reminder_plan_id
                  AND status = 'pending'
                ORDER BY id
                FOR UPDATE
                """
            ),
            {
                "organization_id": organization_id,
                "reminder_plan_id": reminder_plan_id,
            },
        )
    ).all()
    task_ids = tuple(cast(UUID, row[0]) for row in task_rows)
    if not task_ids:
        return

    await session.execute(
        text(
            """
            UPDATE request_engine.communication_tasks
            SET status = 'cancelled',
                revision = revision + 1,
                updated_at = clock_timestamp()
            WHERE organization_id = :organization_id
              AND id = ANY(CAST(:task_ids AS uuid[]))
              AND status = 'pending'
            """
        ),
        {
            "organization_id": organization_id,
            "task_ids": [str(value) for value in task_ids],
        },
    )
    await session.execute(
        text(
            """
            UPDATE request_engine.scheduled_actions
            SET status = 'cancelled',
                updated_at = clock_timestamp()
            WHERE organization_id = :organization_id
              AND owner_module = 'communications'
              AND action_type = 'dispatch_task'
              AND subject_kind = 'CommunicationTask'
              AND subject_id = ANY(CAST(:task_ids AS uuid[]))
              AND status = 'pending'
            """
        ),
        {
            "organization_id": organization_id,
            "task_ids": [str(value) for value in task_ids],
        },
    )


async def database_now(session: AsyncSession) -> datetime:
    return cast(
        datetime,
        (await session.execute(text("SELECT clock_timestamp()"))).scalar_one(),
    )


async def schedule_reminder_occurrence(
    session: AsyncSession,
    *,
    organization_id: UUID,
    reminder_plan_id: UUID,
    plan_revision: int,
    occurrence_at: datetime,
) -> UUID:
    if plan_revision <= 0:
        raise ValueError("plan_revision must be positive")
    return await schedule_action(
        session,
        organization_id=organization_id,
        owner_module="communications",
        action_type=REMINDER_ACTION_TYPE,
        action_version=REMINDER_ACTION_VERSION,
        subject_kind="ReminderPlan",
        subject_id=reminder_plan_id,
        dedupe_key=(
            f"communications:reminder:{reminder_plan_id}:r{plan_revision}:"
            f"{occurrence_at.isoformat()}:v1"
        ),
        execute_at=occurrence_at,
        payload={
            "reminder_plan_id": str(reminder_plan_id),
            "plan_revision": plan_revision,
            "occurrence_at": occurrence_at.isoformat(),
        },
        max_attempts=8,
    )


async def lock_reminder_plan(
    session: AsyncSession,
    *,
    organization_id: UUID,
    reminder_plan_id: UUID,
) -> RowMapping:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT *
                    FROM request_engine.reminder_plans
                    WHERE organization_id = :organization_id
                      AND id = :reminder_plan_id
                    FOR UPDATE
                    """
                ),
                {
                    "organization_id": organization_id,
                    "reminder_plan_id": reminder_plan_id,
                },
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise ReminderPlanNotFound(reminder_plan_id)
    return row


def reminder_plan_from_row(row: RowMapping) -> ReminderPlan:
    schedule_spec = cast(dict[str, object], row["schedule_spec"])
    return ReminderPlan(
        id=cast(UUID, row["id"]),
        subject_party_id=cast(UUID, row["subject_party_id"]),
        purpose=cast(str, row["purpose"]),
        timezone=cast(str, row["timezone"]),
        schedule=parse_daily_schedule(schedule_spec),
        channel_policy=cast(dict[str, object], row["channel_policy"]),
        template_key=cast(str, row["template_key"]),
        template_version=cast(int, row["template_version"]),
        status=ReminderPlanStatus(cast(str, row["status"])),
        revision=cast(int, row["revision"]),
    )


def parse_daily_schedule(schedule_spec: dict[str, object]) -> DailyReminderSchedule:
    if schedule_spec.get("type") != REMINDER_SCHEDULE_TYPE:
        raise ValueError("unsupported reminder schedule type")
    raw_version = schedule_spec.get("version")
    if (
        isinstance(raw_version, bool)
        or not isinstance(raw_version, int)
        or raw_version != REMINDER_SCHEDULE_VERSION
    ):
        raise ValueError("unsupported reminder schedule version")
    raw_times = schedule_spec.get("times")
    raw_lateness = schedule_spec.get("max_lateness_minutes")
    if not isinstance(raw_times, list) or not raw_times:
        raise ValueError("daily reminder schedule times must be a non-empty list")
    if (
        isinstance(raw_lateness, bool)
        or not isinstance(raw_lateness, int)
        or raw_lateness <= 0
        or raw_lateness > 1440
    ):
        raise ValueError("daily reminder max_lateness_minutes must be between 1 and 1440")
    typed_times = cast(list[object], raw_times)
    parsed: list[time] = []
    for raw in typed_times:
        if not isinstance(raw, str):
            raise ValueError("daily reminder schedule time must be a string")
        parsed.append(time.fromisoformat(raw))
    return DailyReminderSchedule(
        times=normalize_daily_times(tuple(parsed)),
        max_lateness_minutes=raw_lateness,
    )


def reminder_plan_to_json(plan: ReminderPlan) -> dict[str, object]:
    return {
        "id": str(plan.id),
        "subject_party_id": str(plan.subject_party_id),
        "purpose": plan.purpose,
        "timezone": plan.timezone,
        "daily_times": [value.isoformat() for value in plan.schedule.times],
        "max_lateness_minutes": plan.schedule.max_lateness_minutes,
        "channel_policy": plan.channel_policy,
        "template_key": plan.template_key,
        "template_version": plan.template_version,
        "status": plan.status.value,
        "revision": plan.revision,
    }


def reminder_plan_from_json(data: dict[str, object]) -> ReminderPlan:
    raw_times = cast(list[object], data["daily_times"])
    parsed_times = tuple(time.fromisoformat(cast(str, raw)) for raw in raw_times)
    return ReminderPlan(
        id=UUID(cast(str, data["id"])),
        subject_party_id=UUID(cast(str, data["subject_party_id"])),
        purpose=cast(str, data["purpose"]),
        timezone=cast(str, data["timezone"]),
        schedule=DailyReminderSchedule(
            times=parsed_times,
            max_lateness_minutes=cast(int, data["max_lateness_minutes"]),
        ),
        channel_policy=cast(dict[str, object], data["channel_policy"]),
        template_key=cast(str, data["template_key"]),
        template_version=cast(int, data["template_version"]),
        status=ReminderPlanStatus(cast(str, data["status"])),
        revision=cast(int, data["revision"]),
    )


def _json(value: dict[str, object]) -> str:
    return json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))
