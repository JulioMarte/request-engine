from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.queue.adapters.db.intake_control_codec import intake_state_from_row
from request_engine.modules.queue.contracts.intake import (
    QueueIntakeControlState,
    SetQueueIntakeControlRequest,
)


async def update_intake_control(
    session: AsyncSession,
    request: SetQueueIntakeControlRequest,
) -> QueueIntakeControlState:
    row = (
        (
            await session.execute(
                text(
                    """
                    UPDATE request_engine.service_queue_intake_controls
                    SET accepting = :accepting, reason = :reason,
                        effective_until = :effective_until,
                        revision = revision + 1,
                        updated_by_principal_id = :principal_id,
                        updated_at = clock_timestamp()
                    WHERE organization_id = :organization_id
                      AND service_queue_id = :service_queue_id
                    RETURNING service_queue_id, accepting, reason,
                              effective_until, revision, updated_at
                    """
                ),
                {
                    "organization_id": request.organization_id,
                    "service_queue_id": request.service_queue_id,
                    "principal_id": request.principal_id,
                    "accepting": request.accepting,
                    "reason": request.reason,
                    "effective_until": request.effective_until,
                },
            )
        )
        .mappings()
        .one()
    )
    return intake_state_from_row(row)
