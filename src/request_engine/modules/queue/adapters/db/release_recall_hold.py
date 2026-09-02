from typing import cast

from request_engine.modules.queue.adapters.db.live_queue_locking import lock_active_queue
from request_engine.modules.queue.adapters.db.live_queue_recording import record_queue_fact
from request_engine.modules.queue.adapters.db.recall_hold_persistence import (
    recall_hold_from_json,
    recall_hold_from_row,
    recall_hold_to_json,
)
from request_engine.modules.queue.adapters.db.recall_hold_read import lock_active_recall_hold
from request_engine.modules.queue.adapters.db.same_day_selection_locking import (
    lock_waiting_entry_in_queue,
)
from request_engine.modules.queue.adapters.db.same_day_selection_persistence import close_current_hold
from request_engine.modules.queue.application.commands.release_recall_hold import (
    ReleaseRecallHoldCommand,
)
from request_engine.modules.queue.contracts.same_day_selection import RecallHold
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)


async def release_recall_hold(
    session_factory: SessionFactory,
    command: ReleaseRecallHoldCommand,
) -> RecallHold | None:
    fingerprint = command_fingerprint(
        "queue.release_recall_hold",
        {"queue_id": command.queue_id, "queue_entry_id": command.queue_entry_id},
    )
    async with tenant_transaction(session_factory, command.organization_id) as session:
        idem, replay = await acquire_idempotency(
            session,
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            capability="queue.release_recall_hold",
            idempotency_key=command.idempotency_key,
            fingerprint=fingerprint,
        )
        if replay is not None:
            data = cast(dict[str, object] | None, replay["hold"])
            return recall_hold_from_json(data) if data else None

        await lock_active_queue(session, command.organization_id, command.queue_id)
        await lock_waiting_entry_in_queue(
            session,
            command.organization_id,
            command.queue_id,
            command.queue_entry_id,
            require_callable=False,
        )
        active = await lock_active_recall_hold(
            session,
            command.organization_id,
            command.queue_entry_id,
        )
        if active is None:
            await complete_idempotency(session, idem, {"hold": None})
            return None

        released = await close_current_hold(
            session,
            organization_id=command.organization_id,
            queue_entry_id=command.queue_entry_id,
            principal_id=command.principal_id,
            release_reason="operator_release",
        )
        if released is None:
            raise RuntimeError("active recall hold disappeared under ServiceQueue lock")
        hold = recall_hold_from_row(released)
        await record_queue_fact(
            session,
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            idempotency_id=idem,
            command_name="queue.release_recall_hold",
            aggregate_id=command.queue_entry_id,
            event_type="queue.recall_hold_released.v1",
            details={"queue_id": str(command.queue_id), "hold_id": str(hold.id)},
            payload={
                "queue_entry_id": str(command.queue_entry_id),
                "queue_id": str(command.queue_id),
                "hold_id": str(hold.id),
            },
        )
        await complete_idempotency(session, idem, {"hold": recall_hold_to_json(hold)})
        return hold
