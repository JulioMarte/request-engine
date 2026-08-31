from datetime import datetime
from typing import cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.application.commands.record_arrival_estimate import (
    RecordArrivalEstimateCommand,
)
from request_engine.modules.booking.application.errors import ArrivalEstimateInvalid


async def db_now(session: AsyncSession) -> datetime:
    return cast(
        datetime,
        (await session.execute(text("SELECT clock_timestamp()"))).scalar_one(),
    )


async def validate_estimate_window(
    session: AsyncSession,
    command: RecordArrivalEstimateCommand,
    *,
    interval_end: datetime,
) -> None:
    """Closed advisory-fact rules, evaluated in-transaction while the reservation
    row lock is held. No lower bound against the interval start: arriving early
    is legal. The DB clock, not the application clock, defines "now". A past
    arrival would be a check-in fact, not an estimate."""

    if command.estimated_arrival_at < await db_now(session):
        raise ArrivalEstimateInvalid(
            command.reservation_id,
            "estimated_arrival_at is in the past; a past arrival is a check-in fact",
        )
    if command.estimated_arrival_at > interval_end:
        raise ArrivalEstimateInvalid(
            command.reservation_id,
            "estimated_arrival_at is after the reservation interval end",
        )
