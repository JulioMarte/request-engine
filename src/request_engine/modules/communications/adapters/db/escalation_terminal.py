"""Terminal lineage fact for the escalation step (docs/v3/36 section 4).

When no usable next channel remains, the ordinal guard is exhausted or the
daily contact fatigue guard refuses, the lineage closes with an
operator-visible ``communication.lineage_unreachable.v1`` outbox fact — never
silence. The aggregate is the failed task that triggered the close; a
replayed close is detected from the already-emitted fact and emits nothing.
"""

from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.communications.adapters.db.escalation_ladder import (
    EscalationOutcome,
)
from request_engine.platform.outbox.postgres import append_outbox


async def close_lineage_terminal(
    session: AsyncSession,
    *,
    organization_id: UUID,
    lineage_id: UUID,
    parent_task_id: UUID,
    trigger: str,
    from_channel: str | None,
    reason: str,
) -> EscalationOutcome:
    if await _lineage_terminal_emitted(
        session,
        organization_id=organization_id,
        parent_task_id=parent_task_id,
    ):
        return EscalationOutcome("no_op", None, None)
    await append_outbox(
        session,
        organization_id=organization_id,
        event_type="communication.lineage_unreachable.v1",
        aggregate_kind="CommunicationTask",
        aggregate_id=parent_task_id,
        payload={
            "lineage_id": str(lineage_id),
            "root_task_id": str(lineage_id),
            "communication_task_id": str(parent_task_id),
            "trigger": trigger,
            "from_channel": from_channel,
            "reason": reason,
        },
    )
    return EscalationOutcome("terminal", None, reason)


async def _lineage_terminal_emitted(
    session: AsyncSession,
    *,
    organization_id: UUID,
    parent_task_id: UUID,
) -> bool:
    return cast(
        bool,
        (
            await session.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM request_engine.outbox_messages"
                    " WHERE organization_id = :organization_id"
                    " AND event_type = 'communication.lineage_unreachable.v1'"
                    " AND aggregate_id = :parent_task_id)"
                ),
                {"organization_id": organization_id, "parent_task_id": parent_task_id},
            )
        ).scalar_one(),
    )
