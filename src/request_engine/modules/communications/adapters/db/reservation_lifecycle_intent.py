from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.contracts.lifecycle import ReservationLifecycleSnapshot
from request_engine.modules.communications.adapters.db.task_store import (
    CommunicationTaskIntent,
    insert_or_reuse_communication_task,
    validate_recipient_and_contact_point,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.scheduling.store import schedule_action


@dataclass(frozen=True, slots=True)
class _DesiredCommunication:
    purpose: str
    template_key: str
    dedupe_key: str
    render_context: dict[str, object]
    not_before: datetime | None
    expires_at: datetime


class PostgresReservationLifecycleNotificationIntent:
    """Materialize reservation communications after Booking has committed."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def reconcile_reservation_notifications(
        self,
        snapshot: ReservationLifecycleSnapshot,
        *,
        source_event_id: UUID,
    ) -> None:
        del source_event_id
        plan = snapshot.notification_plan
        async with tenant_transaction(self._session_factory, snapshot.organization_id) as session:
            db_now = cast(
                datetime,
                (await session.execute(text("SELECT clock_timestamp()"))).scalar_one(),
            )
            desired = _desired_communications(snapshot, db_now)
            await _cancel_stale_pending_for_reservation(
                session,
                snapshot.organization_id,
                snapshot.reservation_id,
                keep_dedupe_keys=tuple(item.dedupe_key for item in desired),
            )
            if snapshot.status != "confirmed" or not desired:
                return
            raw_channels = plan.channel_policy.get("channels")
            if not isinstance(raw_channels, list) or not raw_channels:
                return
            await validate_recipient_and_contact_point(
                session,
                organization_id=snapshot.organization_id,
                recipient_party_id=snapshot.subject_party_id,
                contact_point_id=None,
            )
            for item in desired:
                await _materialize(
                    session,
                    snapshot=snapshot,
                    desired=item,
                    channel_policy=plan.channel_policy,
                    dispatch_at=item.not_before or db_now,
                )

    async def cancel_reservation_notifications(
        self,
        organization_id: UUID,
        reservation_id: UUID,
    ) -> None:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            await _cancel_stale_pending_for_reservation(
                session,
                organization_id,
                reservation_id,
                keep_dedupe_keys=(),
            )


def _desired_communications(
    snapshot: ReservationLifecycleSnapshot,
    db_now: datetime,
) -> tuple[_DesiredCommunication, ...]:
    if snapshot.status != "confirmed" or snapshot.start_at <= db_now:
        return ()
    plan = snapshot.notification_plan
    raw_channels = plan.channel_policy.get("channels")
    if not isinstance(raw_channels, list) or not raw_channels:
        return ()
    context: dict[str, object] = {
        "reservation_id": str(snapshot.reservation_id),
        "start_at": snapshot.start_at.isoformat(),
        "end_at": snapshot.end_at.isoformat(),
        "location_id": str(snapshot.location_id) if snapshot.location_id else None,
    }
    result: list[_DesiredCommunication] = []
    if plan.confirmation:
        result.append(
            _DesiredCommunication(
                purpose="appointment_confirmation",
                template_key="appointment_confirmation",
                dedupe_key=(
                    f"reservation:{snapshot.reservation_id}:confirmation:"
                    f"{snapshot.start_at.isoformat()}:v1"
                ),
                render_context=context,
                not_before=None,
                expires_at=snapshot.start_at,
            )
        )
    for offset in plan.reminders_before_minutes:
        not_before = snapshot.start_at - timedelta(minutes=offset)
        if db_now < not_before < snapshot.start_at:
            result.append(
                _DesiredCommunication(
                    purpose="appointment_reminder",
                    template_key="appointment_reminder",
                    dedupe_key=(
                        f"reservation:{snapshot.reservation_id}:reminder:{offset}:"
                        f"{snapshot.start_at.isoformat()}:v1"
                    ),
                    render_context={**context, "minutes_before": offset},
                    not_before=not_before,
                    expires_at=snapshot.start_at,
                )
            )
    request_offset = plan.attendance_request_before_minutes
    if plan.attendance_confirmation_required and request_offset is not None:
        not_before = snapshot.start_at - timedelta(minutes=request_offset)
        if db_now < not_before < snapshot.start_at:
            result.append(
                _DesiredCommunication(
                    purpose="attendance_confirmation_request",
                    template_key="attendance_confirmation_request",
                    dedupe_key=(
                        f"reservation:{snapshot.reservation_id}:attendance-request:"
                        f"{snapshot.start_at.isoformat()}:v1"
                    ),
                    render_context=context,
                    not_before=not_before,
                    expires_at=snapshot.start_at,
                )
            )
    return tuple(result)


async def _materialize(
    session: AsyncSession,
    *,
    snapshot: ReservationLifecycleSnapshot,
    desired: _DesiredCommunication,
    channel_policy: dict[str, object],
    dispatch_at: datetime,
) -> None:
    task, created = await insert_or_reuse_communication_task(
        session,
        CommunicationTaskIntent(
            organization_id=snapshot.organization_id,
            recipient_party_id=snapshot.subject_party_id,
            contact_point_id=None,
            purpose=desired.purpose,
            source_kind="Reservation",
            source_id=snapshot.reservation_id,
            channel_policy=channel_policy,
            template_key=desired.template_key,
            template_version=1,
            render_context=desired.render_context,
            dedupe_key=desired.dedupe_key,
            not_before=desired.not_before,
            expires_at=desired.expires_at,
        ),
    )
    if not created:
        return
    await schedule_action(
        session,
        organization_id=snapshot.organization_id,
        owner_module="communications",
        action_type="dispatch_task",
        action_version=1,
        subject_kind="CommunicationTask",
        subject_id=task.id,
        dedupe_key=f"communications:dispatch:{task.id}:v1",
        execute_at=dispatch_at,
        payload={"communication_task_id": str(task.id)},
        max_attempts=8,
    )


async def _cancel_stale_pending_for_reservation(
    session: AsyncSession,
    organization_id: UUID,
    reservation_id: UUID,
    *,
    keep_dedupe_keys: tuple[str, ...],
) -> None:
    task_rows = (
        await session.execute(
            text(
                """
                SELECT id
                FROM request_engine.communication_tasks
                WHERE organization_id = :organization_id
                  AND source_kind = 'Reservation'
                  AND source_id = :reservation_id
                  AND status = 'pending'
                  AND (
                      cardinality(CAST(:keep_dedupe_keys AS text[])) = 0
                      OR dedupe_key <> ALL(CAST(:keep_dedupe_keys AS text[]))
                  )
                ORDER BY id
                FOR UPDATE
                """
            ),
            {
                "organization_id": organization_id,
                "reservation_id": reservation_id,
                "keep_dedupe_keys": list(keep_dedupe_keys),
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
            SET status = 'cancelled', revision = revision + 1,
                updated_at = clock_timestamp()
            WHERE organization_id = :organization_id
              AND id = ANY(CAST(:task_ids AS uuid[]))
              AND status = 'pending'
            """
        ),
        {"organization_id": organization_id, "task_ids": [str(value) for value in task_ids]},
    )
    await session.execute(
        text(
            """
            UPDATE request_engine.scheduled_actions
            SET status = 'cancelled', updated_at = clock_timestamp()
            WHERE organization_id = :organization_id
              AND owner_module = 'communications'
              AND subject_kind = 'CommunicationTask'
              AND subject_id = ANY(CAST(:task_ids AS uuid[]))
              AND status = 'pending'
            """
        ),
        {"organization_id": organization_id, "task_ids": [str(value) for value in task_ids]},
    )
