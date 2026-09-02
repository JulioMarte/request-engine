from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.queue.adapters.db.live_queue_recording import record_queue_fact
from request_engine.modules.queue.application.commands.recall_hold import RecallHoldCommand


async def record_recall_hold(
    session: AsyncSession,
    *,
    command: RecallHoldCommand,
    idempotency_id: UUID,
    queue_entry_revision: int,
) -> None:
    await record_queue_fact(
        session,
        organization_id=command.organization_id,
        principal_id=command.principal_id,
        idempotency_id=idempotency_id,
        command_name="queue.recall_hold",
        aggregate_id=command.queue_entry_id,
        event_type="queue.recall_hold_recorded.v1",
        details={
            "queue_id": str(command.queue_id),
            "hold_kind": command.kind.value,
            "queue_entry_revision": queue_entry_revision,
        },
        payload={
            "queue_entry_id": str(command.queue_entry_id),
            "queue_id": str(command.queue_id),
            "hold_kind": command.kind.value,
            "release_at": command.release_at.isoformat() if command.release_at else None,
            "queue_entry_revision": queue_entry_revision,
        },
    )
