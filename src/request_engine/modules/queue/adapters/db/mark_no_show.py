from typing import cast
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.queue.adapters.db.live_queue_locking import (
    lock_active_queue,
    lock_queue_entry,
    probe_queue_entry,
)
from request_engine.modules.queue.adapters.db.live_queue_recording import record_queue_fact
from request_engine.modules.queue.adapters.db.live_queue_serialization import (
    entry_from_json,
    entry_from_row,
    entry_to_json,
)
from request_engine.modules.queue.application.errors import (
    QueueEntryNotCancellable,
    QueueEntryRevisionConflict,
)
from request_engine.modules.queue.application.live_commands import MarkNoShowCommand
from request_engine.modules.queue.contracts.live_queue import LiveQueueEntry
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)


async def mark_no_show(
    session_factory: SessionFactory,
    command: MarkNoShowCommand,
) -> LiveQueueEntry:
    fingerprint = command_fingerprint(
        "queue.mark_no_show",
        {
            "queue_entry_id": command.queue_entry_id,
            "expected_revision": command.expected_revision,
        },
    )
    async with tenant_transaction(session_factory, command.organization_id) as session:
        idem, replay = await acquire_idempotency(
            session,
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            capability="queue.mark_no_show",
            idempotency_key=command.idempotency_key,
            fingerprint=fingerprint,
        )
        if replay is not None:
            return entry_from_json(cast(dict[str, object], replay["entry"]))
        probe = await probe_queue_entry(
            session,
            command.organization_id,
            command.queue_entry_id,
        )
        if probe is None:
            raise QueueEntryNotCancellable(command.queue_entry_id, "missing")
        await lock_active_queue(
            session,
            command.organization_id,
            cast(UUID, probe["service_queue_id"]),
        )
        row = await lock_queue_entry(
            session,
            command.organization_id,
            command.queue_entry_id,
        )
        actual_revision = cast(int, row["revision"])
        if actual_revision != command.expected_revision:
            raise QueueEntryRevisionConflict(
                command.queue_entry_id,
                command.expected_revision,
                actual_revision,
            )
        current = cast(str, row["status"])
        if current != "called":
            raise QueueEntryNotCancellable(command.queue_entry_id, current)
        exists = (
            await session.execute(
                text(
                    "SELECT 1 FROM request_engine.service_sessions "
                    "WHERE organization_id=:organization_id AND queue_entry_id=:entry_id"
                ),
                {
                    "organization_id": command.organization_id,
                    "entry_id": command.queue_entry_id,
                },
            )
        ).first()
        if exists is not None:
            raise QueueEntryNotCancellable(
                command.queue_entry_id,
                "service_session_exists",
            )
        updated = (
            await session.execute(
                text(
                    "UPDATE request_engine.queue_entries "
                    "SET status='no_show',revision=revision+1,"
                    "updated_at=clock_timestamp() "
                    "WHERE organization_id=:organization_id AND id=:entry_id "
                    "RETURNING id,service_queue_id,subject_party_id,reservation_id,"
                    "offering_id,status,arrived_at,admitted_at,called_at,"
                    "expected_workload_classification_id,revision"
                ),
                {
                    "organization_id": command.organization_id,
                    "entry_id": command.queue_entry_id,
                },
            )
        ).mappings().one()
        result = entry_from_row(updated)
        details: dict[str, object] = {"queue_id": str(result.queue_id)}
        await record_queue_fact(
            session,
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            idempotency_id=idem,
            command_name="queue.mark_no_show",
            aggregate_id=result.id,
            event_type="queue.entry_no_show.v1",
            details=details,
            payload={"queue_entry_id": str(result.id), "queue_id": str(result.queue_id)},
        )
        await complete_idempotency(session, idem, {"entry": entry_to_json(result)})
        return result
