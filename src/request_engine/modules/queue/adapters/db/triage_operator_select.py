from typing import cast

from sqlalchemy import text

from request_engine.modules.queue.adapters.db.live_queue_locking import lock_active_queue
from request_engine.modules.queue.adapters.db.triage_audit import append_triage_audit
from request_engine.modules.queue.adapters.db.triage_called import mark_entry_called
from request_engine.modules.queue.adapters.db.triage_codec import result_from_json, result_to_json
from request_engine.modules.queue.adapters.db.triage_entry import (
    lock_waiting_entry,
    queue_id_for_entry,
)
from request_engine.modules.queue.adapters.db.triage_idempotency import (
    acquire,
    complete,
    fingerprint,
)
from request_engine.modules.queue.application.commands.triage import OperatorSelectCommand
from request_engine.modules.queue.contracts.triage import QueueTriageResult
from request_engine.platform.db.session import SessionFactory, tenant_transaction


async def operator_select(
    session_factory: SessionFactory,
    command: OperatorSelectCommand,
) -> QueueTriageResult:
    command_fingerprint = fingerprint(
        "queue.operator_select",
        {
            "queue_entry_id": command.queue_entry_id,
            "reason": command.reason.value,
            "expected_revision": command.expected_revision,
        },
    )
    async with tenant_transaction(session_factory, command.organization_id) as session:
        idem_id, replay = await acquire(
            session,
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            capability="queue.operator_select",
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
        await session.execute(
            text(
                """
                UPDATE request_engine.queue_entry_recall_holds
                   SET released_at = clock_timestamp(), release_kind = 'operator_select'
                 WHERE organization_id = :organization_id
                   AND queue_entry_id = :entry_id AND released_at IS NULL
                """
            ),
            {"organization_id": command.organization_id, "entry_id": command.queue_entry_id},
        )
        await session.execute(
            text(
                """
                UPDATE request_engine.queue_entry_skips
                   SET consumed_at = clock_timestamp(), consumed_by_entry_id = :entry_id
                 WHERE organization_id = :organization_id
                   AND queue_entry_id = :entry_id AND consumed_at IS NULL
                """
            ),
            {"organization_id": command.organization_id, "entry_id": command.queue_entry_id},
        )
        await session.execute(
            text(
                """
                INSERT INTO request_engine.queue_entry_operator_selections (
                    organization_id, queue_entry_id, reason, selected_by_principal_id
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
        revision = await mark_entry_called(session, command.organization_id, command.queue_entry_id)
        result = QueueTriageResult(
            command.queue_entry_id,
            queue_id,
            "called",
            revision,
            "operator_select",
            command.reason.value,
        )
        await append_triage_audit(
            session,
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            command_name="queue.operator_select",
            entry_id=command.queue_entry_id,
            details={"queue_id": str(queue_id), "reason": command.reason.value},
            idempotency_id=idem_id,
        )
        await complete(session, idem_id, {"result": result_to_json(result)})
        return result
