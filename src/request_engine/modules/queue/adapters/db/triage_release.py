from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.queue.adapters.db.live_queue_locking import lock_active_queue
from request_engine.modules.queue.adapters.db.triage_audit import append_triage_audit
from request_engine.modules.queue.adapters.db.triage_codec import result_from_json, result_to_json
from request_engine.modules.queue.adapters.db.triage_entry import (
    bump_waiting_revision,
    expire_time_hold,
    lock_waiting_entry,
    queue_id_for_entry,
)
from request_engine.modules.queue.adapters.db.triage_idempotency import (
    acquire,
    complete,
    fingerprint,
)
from request_engine.modules.queue.application.commands.triage import ReleaseRecallHoldCommand
from request_engine.modules.queue.application.triage_errors import (
    QueueHoldNotActive,
    RecallHoldConflict,
)
from request_engine.modules.queue.contracts.triage import QueueTriageResult
from request_engine.platform.db.session import SessionFactory, tenant_transaction


async def release_recall_hold(
    session_factory: SessionFactory,
    command: ReleaseRecallHoldCommand,
) -> QueueTriageResult:
    command_fingerprint = fingerprint(
        "queue.release_recall_hold",
        {
            "queue_entry_id": command.queue_entry_id,
            "hold_id": command.hold_id,
            "expected_revision": command.expected_revision,
        },
    )
    async with tenant_transaction(session_factory, command.organization_id) as session:
        idem_id, replay = await acquire(
            session,
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            capability="queue.release_recall_hold",
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
        hold_id = await lock_active_recall_hold(
            session, command.organization_id, command.queue_entry_id
        )
        if hold_id is None:
            raise QueueHoldNotActive(command.queue_entry_id)
        if hold_id != command.hold_id:
            raise RecallHoldConflict(command.queue_entry_id)
        await release_hold(session, command.organization_id, command.hold_id)
        revision = await bump_waiting_revision(
            session, command.organization_id, command.queue_entry_id
        )
        result = QueueTriageResult(
            command.queue_entry_id,
            queue_id,
            "waiting",
            revision,
            "release_recall_hold",
            None,
            None,
        )
        await append_triage_audit(
            session,
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            command_name="queue.release_recall_hold",
            entry_id=command.queue_entry_id,
            details={"queue_id": str(queue_id), "hold_id": str(command.hold_id)},
            idempotency_id=idem_id,
        )
        await complete(session, idem_id, {"result": result_to_json(result)})
        return result


async def lock_active_recall_hold(
    session: AsyncSession,
    organization_id: UUID,
    entry_id: UUID,
) -> UUID | None:
    row = (
        await session.execute(
            text(
                """
                SELECT id
                  FROM request_engine.queue_entry_recall_holds
                 WHERE organization_id = :organization_id
                   AND queue_entry_id = :entry_id AND released_at IS NULL
                 FOR UPDATE
                """
            ),
            {"organization_id": organization_id, "entry_id": entry_id},
        )
    ).first()
    if row is None:
        return None
    return cast(UUID, row[0])


async def release_hold(
    session: AsyncSession,
    organization_id: UUID,
    hold_id: UUID,
) -> None:
    await session.execute(
        text(
            """
            UPDATE request_engine.queue_entry_recall_holds
               SET released_at = clock_timestamp(), release_kind = 'operator_release'
             WHERE organization_id = :organization_id
               AND id = :hold_id AND released_at IS NULL
            """
        ),
        {"organization_id": organization_id, "hold_id": hold_id},
    )
