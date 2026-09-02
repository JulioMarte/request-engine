from typing import cast

from request_engine.modules.queue.adapters.db.live_queue_locking import lock_active_queue
from request_engine.modules.queue.adapters.db.live_queue_recording import record_queue_fact
from request_engine.modules.queue.adapters.db.same_day_selection_codec import (
    queue_entry_from_json,
    queue_entry_from_row,
    queue_entry_to_json,
)
from request_engine.modules.queue.adapters.db.same_day_selection_locking import (
    lock_waiting_entry_in_queue,
)
from request_engine.modules.queue.adapters.db.same_day_selection_persistence import (
    call_waiting_entry,
    insert_selection_fact,
)
from request_engine.modules.queue.application.commands.operator_select import OperatorSelectCommand
from request_engine.modules.queue.application.errors import QueueEntryRevisionConflict
from request_engine.modules.queue.contracts.service_queue import QueueEntry
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)


async def operator_select(
    session_factory: SessionFactory,
    command: OperatorSelectCommand,
) -> QueueEntry:
    fingerprint = command_fingerprint(
        "queue.operator_select",
        {
            "queue_id": command.queue_id,
            "queue_entry_id": command.queue_entry_id,
            "expected_revision": command.expected_revision,
            "reason": command.reason.value,
        },
    )
    async with tenant_transaction(session_factory, command.organization_id) as session:
        idem, replay = await acquire_idempotency(
            session,
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            capability="queue.operator_select",
            idempotency_key=command.idempotency_key,
            fingerprint=fingerprint,
        )
        if replay is not None:
            return queue_entry_from_json(cast(dict[str, object], replay["entry"]))

        await lock_active_queue(session, command.organization_id, command.queue_id)
        target = await lock_waiting_entry_in_queue(
            session,
            command.organization_id,
            command.queue_id,
            command.queue_entry_id,
            require_callable=True,
        )
        actual_revision = cast(int, target["revision"])
        if actual_revision != command.expected_revision:
            raise QueueEntryRevisionConflict(
                command.queue_entry_id,
                command.expected_revision,
                actual_revision,
            )

        entry = queue_entry_from_row(
            await call_waiting_entry(session, command.organization_id, command.queue_entry_id)
        )
        await insert_selection_fact(
            session,
            organization_id=command.organization_id,
            queue_id=command.queue_id,
            queue_entry_id=entry.id,
            selection_kind="operator_select",
            reason=command.reason.value,
            principal_id=command.principal_id,
        )
        await record_queue_fact(
            session,
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            idempotency_id=idem,
            command_name="queue.operator_select",
            aggregate_id=entry.id,
            event_type="queue.entry_called.v1",
            details={"queue_id": str(command.queue_id), "reason": command.reason.value},
            payload={
                "queue_entry_id": str(entry.id),
                "queue_id": str(entry.queue_id),
                "subject_party_id": str(entry.subject_party_id),
                "called_at": entry.called_at.isoformat() if entry.called_at else None,
                "selection_kind": "operator_select",
            },
        )
        await complete_idempotency(session, idem, {"entry": queue_entry_to_json(entry)})
        return entry
