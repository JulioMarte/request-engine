from typing import cast
from uuid import UUID

from request_engine.modules.queue.adapters.db.live_queue_locking import lock_active_queue
from request_engine.modules.queue.adapters.db.live_queue_recording import record_queue_fact
from request_engine.modules.queue.adapters.db.recall_hold_persistence import (
    recall_hold_from_json,
    recall_hold_from_row,
    recall_hold_to_json,
)
from request_engine.modules.queue.adapters.db.recall_hold_read import lock_current_recall_hold
from request_engine.modules.queue.adapters.db.release_recall_hold_persistence import (
    release_hold_by_id,
)
from request_engine.modules.queue.adapters.db.same_day_selection_locking import (
    lock_waiting_entry_in_queue,
)
from request_engine.modules.queue.adapters.db.same_day_selection_revision import (
    bump_waiting_entry_revision,
)
from request_engine.modules.queue.application.commands.release_recall_hold import (
    ReleaseRecallHoldCommand,
)
from request_engine.modules.queue.application.errors import QueueEntryRevisionConflict
from request_engine.modules.queue.application.same_day_selection_errors import RecallHoldConflict
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
        {
            "queue_id": command.queue_id,
            "queue_entry_id": command.queue_entry_id,
            "hold_id": command.hold_id,
            "expected_revision": command.expected_revision,
        },
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
        target = await lock_waiting_entry_in_queue(
            session,
            command.organization_id,
            command.queue_id,
            command.queue_entry_id,
            require_callable=False,
        )
        actual_revision = cast(int, target["revision"])
        if actual_revision != command.expected_revision:
            raise QueueEntryRevisionConflict(
                command.queue_entry_id,
                command.expected_revision,
                actual_revision,
            )
        active = await lock_current_recall_hold(
            session,
            command.organization_id,
            command.queue_entry_id,
        )
        if active is None:
            await complete_idempotency(session, idem, {"hold": None})
            return None
        active_hold_id = cast(UUID, active["id"])
        if active_hold_id != command.hold_id:
            raise RecallHoldConflict(command.queue_entry_id, command.hold_id, active_hold_id)

        released = await release_hold_by_id(
            session,
            organization_id=command.organization_id,
            queue_entry_id=command.queue_entry_id,
            hold_id=command.hold_id,
            principal_id=command.principal_id,
        )
        if released is None:
            raise RuntimeError("active recall hold disappeared under ServiceQueue lock")
        revision = await bump_waiting_entry_revision(
            session,
            command.organization_id,
            command.queue_entry_id,
        )
        hold = recall_hold_from_row(released, revision)
        await record_queue_fact(
            session,
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            idempotency_id=idem,
            command_name="queue.release_recall_hold",
            aggregate_id=command.queue_entry_id,
            event_type="queue.recall_hold_released.v1",
            details={
                "queue_id": str(command.queue_id),
                "hold_id": str(hold.id),
                "queue_entry_revision": revision,
            },
            payload={
                "queue_entry_id": str(command.queue_entry_id),
                "queue_id": str(command.queue_id),
                "hold_id": str(hold.id),
                "queue_entry_revision": revision,
            },
        )
        await complete_idempotency(session, idem, {"hold": recall_hold_to_json(hold)})
        return hold
