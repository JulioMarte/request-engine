from typing import cast

from sqlalchemy import text

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
from request_engine.modules.queue.adapters.db.triage_selection import lock_next_eligible_entry
from request_engine.modules.queue.application.commands.triage import SkipCommand
from request_engine.modules.queue.application.triage_errors import (
    QueueEntryAlreadyHeld,
    QueueEntryAlreadySkipped,
    QueueEntryNotCurrentHead,
)
from request_engine.modules.queue.contracts.triage import QueueTriageResult
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)


async def skip(
    session_factory: SessionFactory,
    command: SkipCommand,
) -> QueueTriageResult:
    fingerprint = command_fingerprint(
        "queue.skip",
        {
            "queue_entry_id": command.queue_entry_id,
            "reason": command.reason.value,
            "expected_revision": command.expected_revision,
        },
    )
    async with tenant_transaction(session_factory, command.organization_id) as session:
        idem_id, replay = await acquire_idempotency(
            session,
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            capability="queue.skip",
            idempotency_key=command.idempotency_key,
            fingerprint=fingerprint,
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
        if gate == "hold":
            raise QueueEntryAlreadyHeld(command.queue_entry_id)
        if gate == "skip":
            raise QueueEntryAlreadySkipped(command.queue_entry_id)
        head_id = await lock_next_eligible_entry(session, command.organization_id, queue_id)
        if head_id != command.queue_entry_id:
            raise QueueEntryNotCurrentHead(command.queue_entry_id)
        await session.execute(
            text(
                """
                INSERT INTO request_engine.queue_entry_skips (
                    organization_id, queue_entry_id, reason, created_by_principal_id
                ) VALUES (:organization_id, :entry_id, :reason, :principal_id)
                """
            ),
            {
                "organization_id": command.organization_id,
                "entry_id": command.queue_entry_id,
                "reason": command.reason.value,
                "principal_id": command.principal_id,
            },
        )
        revision = await bump_waiting_revision(
            session, command.organization_id, command.queue_entry_id
        )
        result = QueueTriageResult(
            command.queue_entry_id,
            queue_id,
            "waiting",
            revision,
            "skip",
            command.reason.value,
        )
        await append_triage_audit(
            session,
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            command_name="queue.skip",
            entry_id=command.queue_entry_id,
            details={"queue_id": str(queue_id), "reason": command.reason.value},
            idempotency_id=idem_id,
        )
        await complete_idempotency(session, idem_id, {"result": result_to_json(result)})
        return result
