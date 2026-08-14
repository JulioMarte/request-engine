from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.contracts.lifecycle import ReservationLifecycleSnapshot
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.scheduling.store import schedule_action

NO_SHOW_ACTION_TYPE = "evaluate_no_show"
NO_SHOW_ACTION_VERSION = 1


class PostgresReservationLifecycleScheduling:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def reconcile_reservation_schedule(
        self,
        snapshot: ReservationLifecycleSnapshot,
        *,
        source_event_id: UUID,
    ) -> None:
        async with tenant_transaction(self._session_factory, snapshot.organization_id) as session:
            await _cancel_pending(session, snapshot.organization_id, snapshot.reservation_id)
            if snapshot.status != "confirmed" or snapshot.no_show_after_minutes is None:
                return
            execute_at = snapshot.start_at + timedelta(
                minutes=snapshot.no_show_after_minutes
            )
            db_now = cast(
                datetime,
                (await session.execute(text("SELECT clock_timestamp()"))).scalar_one(),
            )
            if execute_at <= db_now:
                execute_at = db_now
            await schedule_action(
                session,
                organization_id=snapshot.organization_id,
                owner_module="booking",
                action_type=NO_SHOW_ACTION_TYPE,
                action_version=NO_SHOW_ACTION_VERSION,
                subject_kind="Reservation",
                subject_id=snapshot.reservation_id,
                dedupe_key=(
                    f"booking:no-show:{snapshot.reservation_id}:"
                    f"{snapshot.start_at.isoformat()}:v1"
                ),
                execute_at=execute_at,
                payload={
                    "reservation_id": str(snapshot.reservation_id),
                    "source_event_id": str(source_event_id),
                },
                max_attempts=8,
            )

    async def cancel_reservation_schedule(
        self,
        organization_id: UUID,
        reservation_id: UUID,
    ) -> None:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            await _cancel_pending(session, organization_id, reservation_id)


async def _cancel_pending(
    session: AsyncSession,
    organization_id: UUID,
    reservation_id: UUID,
) -> None:
    await session.execute(
        text(
            """
            UPDATE request_engine.scheduled_actions
            SET status = 'cancelled', updated_at = clock_timestamp()
            WHERE organization_id = :organization_id
              AND owner_module = 'booking'
              AND action_type = :action_type
              AND subject_kind = 'Reservation'
              AND subject_id = :reservation_id
              AND status = 'pending'
            """
        ),
        {
            "organization_id": organization_id,
            "reservation_id": reservation_id,
            "action_type": NO_SHOW_ACTION_TYPE,
        },
    )
