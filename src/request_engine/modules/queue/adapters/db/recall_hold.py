from typing import cast

from request_engine.modules.queue.adapters.db.live_queue_locking import lock_active_queue
from request_engine.modules.queue.adapters.db.live_queue_recording import record_queue_fact
from request_engine.modules.queue.adapters.db.recall_hold_persistence import (
    database_clock,
    insert_recall_hold,
    recall_hold_from_json,
    recall_hold_to_json,
)
from request_engine.modules.queue.adapters.db.recall_hold_validation import (
    validate_recall_hold_shape,
)
from request_engine.modules.queue.adapters.db.same_day_selection_locking import (
    lock_waiting_entry_in_queue,
)
from request_engine.modules.queue.adapters.db.same_day_selection_persistence import close_current_hold
from request_engine.modules.queue.adapters.db.same_day_selection_revision import (
    bump_waiting_entry_revision,
)
from request_engine.modules.queue.application.commands.recall_hold import RecallHoldCommand
from request_engine.modules.queue.application.errors import QueueEntryRevisionConflict
from request_engine.modules.queue.application.same_day_selection_errors import RecallHoldInvalid
from request_engine.modules.queue.contracts.same_day_selection import RecallHold, RecallHoldKind
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)


async def recall_hold(
    session_factory: SessionFactory,
    command: RecallHoldCommand,
) -> RecallHold:
    validate_recall_hold_shape(command)
    fingerprint = command_fingerprint(
        "queue.recall_hold",
        {
            "queue_id": command.queue_id,
            "queue_entry_id": command.queue_entry_id,
            "expected_revision": command.expected_revision,
            "kind": command.kind.value,
            "release_at": command.release_at,
            "reason": command.reason,
        },
    )
    async with tenant_transaction(session_factory, command.organization_id) as session:
        idem, replay = await acquire_idempotency(
            session,
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            capability="queue.recall_hold",
            idempotency_key=command.idempotency_key,
            fingerprint=fingerprint,
        )
        if replay is not None:
            return recall_hold_from_json(cast(dict[str, object], replay["hold"]))

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
        if command.kind is RecallHoldKind.UNTIL_TIME:
            now = await database_clock(session)
            if command.release_at is None or command.release_at <= now:
                raise RecallHoldInvalid("until_time release_at must be after the database clock")

        await close_current_hold(
            session,
            organization_id=command.organization_id,
            queue_entry_id=command.queue_entry_id,
            principal_id=command.principal_id,
            release_reason="replaced",
        )
        revision = await bump_waiting_entry_revision(
            session,
            command.organization_id,
            command.queue_entry_id,
        )
        hold = await insert_recall_hold(
            session,
            organization_id=command.organization_id,
            queue_id=command.queue_id,
            queue_entry_id=command.queue_entry_id,
            queue_entry_revision=revision,
            kind=command.kind,
            release_at=command.release_at,
            reason=command.reason,
            principal_id=command.principal_id,
        )
        await record_queue_fact(
            session,
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            idempotency_id=idem,
            command_name="queue.recall_hold",
            aggregate_id=command.queue_entry_id,
            event_type="queue.recall_hold_recorded.v1",
            details={
                "queue_id": str(command.queue_id),
                "hold_kind": command.kind.value,
                "queue_entry_revision": revision,
            },
            payload={
                "queue_entry_id": str(command.queue_entry_id),
                "queue_id": str(command.queue_id),
                "hold_kind": command.kind.value,
                "release_at": command.release_at.isoformat() if command.release_at else None,
                "queue_entry_revision": revision,
            },
        )
        await complete_idempotency(session, idem, {"hold": recall_hold_to_json(hold)})
        return hold
