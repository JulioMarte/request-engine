from typing import cast

from request_engine.modules.queue.adapters.db.live_queue_locking import lock_active_queue
from request_engine.modules.queue.adapters.db.live_queue_recording import record_queue_fact
from request_engine.modules.queue.adapters.db.same_day_selection_codec import (
    queue_entry_from_row,
    skip_result_from_json,
    skip_result_to_json,
)
from request_engine.modules.queue.adapters.db.same_day_selection_locking import (
    lock_eligible_fifo_entries,
)
from request_engine.modules.queue.adapters.db.same_day_selection_persistence import (
    call_waiting_entry,
    insert_selection_fact,
)
from request_engine.modules.queue.application.commands.skip_queue_head import SkipQueueHeadCommand
from request_engine.modules.queue.contracts.same_day_selection import SkipResult
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)
from request_engine.platform.outbox.postgres import append_outbox


async def skip_queue_head(
    session_factory: SessionFactory,
    command: SkipQueueHeadCommand,
) -> SkipResult | None:
    fingerprint = command_fingerprint(
        "queue.skip",
        {"queue_id": command.queue_id, "reason": command.reason.value},
    )
    async with tenant_transaction(session_factory, command.organization_id) as session:
        idem, replay = await acquire_idempotency(
            session,
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            capability="queue.skip",
            idempotency_key=command.idempotency_key,
            fingerprint=fingerprint,
        )
        if replay is not None:
            data = cast(dict[str, object] | None, replay["result"])
            return skip_result_from_json(data) if data else None

        await lock_active_queue(session, command.organization_id, command.queue_id)
        eligible = await lock_eligible_fifo_entries(
            session,
            command.organization_id,
            command.queue_id,
            limit=2,
        )
        if not eligible:
            await complete_idempotency(session, idem, {"result": None})
            return None

        skipped_entry_id = eligible[0]
        called_entry = None
        if len(eligible) == 2:
            called_entry = queue_entry_from_row(
                await call_waiting_entry(session, command.organization_id, eligible[1])
            )

        await insert_selection_fact(
            session,
            organization_id=command.organization_id,
            queue_id=command.queue_id,
            queue_entry_id=skipped_entry_id,
            selection_kind="skip",
            reason=command.reason.value,
            principal_id=command.principal_id,
            called_queue_entry_id=called_entry.id if called_entry else None,
        )
        await record_queue_fact(
            session,
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            idempotency_id=idem,
            command_name="queue.skip",
            aggregate_id=skipped_entry_id,
            event_type="queue.entry_skipped.v1",
            details={"queue_id": str(command.queue_id), "reason": command.reason.value},
            payload={
                "queue_entry_id": str(skipped_entry_id),
                "queue_id": str(command.queue_id),
                "called_queue_entry_id": str(called_entry.id) if called_entry else None,
            },
        )
        if called_entry is not None:
            await append_outbox(
                session,
                organization_id=command.organization_id,
                event_type="queue.entry_called.v1",
                aggregate_kind="QueueEntry",
                aggregate_id=called_entry.id,
                payload={
                    "queue_entry_id": str(called_entry.id),
                    "queue_id": str(called_entry.queue_id),
                    "subject_party_id": str(called_entry.subject_party_id),
                    "called_at": (
                        called_entry.called_at.isoformat() if called_entry.called_at else None
                    ),
                    "selection_kind": "skip",
                },
            )

        result = SkipResult(skipped_entry_id=skipped_entry_id, called_entry=called_entry)
        await complete_idempotency(session, idem, {"result": skip_result_to_json(result)})
        return result
