from typing import cast

from request_engine.modules.queue.adapters.db.live_queue_locking import lock_active_queue
from request_engine.modules.queue.adapters.db.triage_audit import append_triage_audit
from request_engine.modules.queue.adapters.db.triage_codec import result_from_json, result_to_json
from request_engine.modules.queue.adapters.db.triage_entry import (
    bump_waiting_revision,
    expire_time_hold,
    lock_waiting_entry,
    queue_id_for_entry,
)
from request_engine.modules.queue.adapters.db.triage_gate import active_gate
from request_engine.modules.queue.adapters.db.triage_hold_store import insert_recall_hold
from request_engine.modules.queue.adapters.db.triage_hold_validation import validate_recall_hold
from request_engine.modules.queue.adapters.db.triage_idempotency import (
    acquire,
    complete,
    fingerprint,
)
from request_engine.modules.queue.application.commands.triage import RecallHoldCommand
from request_engine.modules.queue.application.triage_errors import (
    QueueEntryAlreadyHeld,
    QueueEntryAlreadySkipped,
)
from request_engine.modules.queue.contracts.triage import QueueTriageResult
from request_engine.platform.db.session import SessionFactory, tenant_transaction


async def recall_hold(
    session_factory: SessionFactory,
    command: RecallHoldCommand,
) -> QueueTriageResult:
    validate_recall_hold(command)
    command_fingerprint = fingerprint(
        "queue.recall_hold",
        {
            "queue_entry_id": command.queue_entry_id,
            "condition_kind": command.condition_kind.value,
            "until_at": command.until_at,
            "event_key": command.event_key,
            "reason": command.reason,
            "expected_revision": command.expected_revision,
        },
    )
    async with tenant_transaction(session_factory, command.organization_id) as session:
        idem_id, replay = await acquire(
            session,
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            capability="queue.recall_hold",
            idempotency_key=command.idempotency_key,
            command_fingerprint=command_fingerprint,
        )
        if replay is not None:
            return result_from_json(cast(dict[str, object], replay["result"]))
        queue_id = await queue_id_for_entry(
            session, command.organization_id, command.queue_entry_id
        )
        await lock_active_queue(session, command.organization_id, queue_id)
        await lock_waiting_entry(
            session,
            command.organization_id,
            queue_id,
            command.queue_entry_id,
            command.expected_revision,
        )
        await expire_time_hold(session, command.organization_id, command.queue_entry_id)
        gate = await active_gate(session, command.organization_id, command.queue_entry_id)
        if gate == "skip":
            raise QueueEntryAlreadySkipped(command.queue_entry_id)
        if gate == "hold":
            raise QueueEntryAlreadyHeld(command.queue_entry_id)
        hold = await insert_recall_hold(session, command)
        revision = await bump_waiting_revision(
            session, command.organization_id, command.queue_entry_id
        )
        result = QueueTriageResult(
            command.queue_entry_id,
            queue_id,
            "waiting",
            revision,
            "recall_hold",
            command.reason,
            hold,
        )
        await append_triage_audit(
            session,
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            command_name="queue.recall_hold",
            entry_id=command.queue_entry_id,
            details={
                "queue_id": str(queue_id),
                "condition_kind": command.condition_kind.value,
            },
            idempotency_id=idem_id,
        )
        await complete(session, idem_id, {"result": result_to_json(result)})
        return result
