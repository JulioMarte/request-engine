"""Served-visit guard for Reservation lifecycle commands.

A Reservation whose visit was served has consumed its commitment: cancelling it
would release capacity for time already spent, and rescheduling it would plan a
second visit under the same commitment. The served-visit fact is a QueueEntry of
the Reservation in ``completed`` status; it is reached only through the
delivery-owned serving -> completed transition that completes the
ServiceSession in the same transaction (see ``request_read.reservation_day_v1``).

Booking reads that queue fact directly in its own transaction because the
dependency direction is queue -> booking (booking cannot import queue
contracts) and the guard must be atomic with the lifecycle mutation.
"""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.application.errors import ReservationAlreadyServed


async def ensure_reservation_not_served(
    session: AsyncSession, organization_id: UUID, reservation_id: UUID
) -> None:
    """Refuse a served Reservation; call after locking the Reservation FOR UPDATE.

    Lock order: Reservation (FOR UPDATE, by the caller) -> the Reservation's
    serving/completed QueueEntries (FOR SHARE) -> Resources. Service completion
    locks ServiceQueue -> QueueEntry -> Resource and never a Reservation, so the
    order is acyclic. FOR SHARE makes the guard linearizable with completion: an
    in-flight serving -> completed transition is waited for and re-read, so a
    cancel/reschedule never commits after the visit it would undo was served.
    """
    rows = (
        await session.execute(
            text(
                """
                SELECT status
                FROM request_engine.queue_entries
                WHERE organization_id = :organization_id
                  AND reservation_id = :reservation_id
                  AND status IN ('serving', 'completed')
                ORDER BY id
                FOR SHARE
                """
            ),
            {"organization_id": organization_id, "reservation_id": reservation_id},
        )
    ).all()
    if any(row[0] == "completed" for row in rows):
        raise ReservationAlreadyServed(reservation_id)
