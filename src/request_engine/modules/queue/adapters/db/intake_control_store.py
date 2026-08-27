from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.queue.adapters.db.intake_control_codec import intake_state_from_row
from request_engine.modules.queue.contracts.intake import (
    QueueIntakeControlState,
    QueueIntakeStopped,
)


async def load_intake_control(
    session: AsyncSession,
    *,
    organization_id: UUID,
    service_queue_id: UUID,
    lock: bool,
) -> QueueIntakeControlState:
    suffix = " FOR UPDATE" if lock else ""
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT service_queue_id, accepting, reason,
                           effective_until, revision, updated_at
                    FROM request_engine.service_queue_intake_controls
                    WHERE organization_id = :organization_id
                      AND service_queue_id = :service_queue_id
                    """
                    + suffix
                ),
                {"organization_id": organization_id, "service_queue_id": service_queue_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise LookupError(f"ServiceQueue {service_queue_id} intake control is not configured")
    return intake_state_from_row(cast(RowMapping, row))


async def require_queue_accepting_intake(
    session: AsyncSession,
    *,
    organization_id: UUID,
    service_queue_id: UUID,
) -> QueueIntakeControlState:
    state = await load_intake_control(
        session,
        organization_id=organization_id,
        service_queue_id=service_queue_id,
        lock=True,
    )
    if state.accepting:
        return state
    if state.effective_until is not None:
        now = cast(datetime, (await session.execute(text("SELECT clock_timestamp()"))).scalar_one())
        if state.effective_until <= now:
            return state
    raise QueueIntakeStopped(service_queue_id, state.reason)
