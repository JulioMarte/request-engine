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
from request_engine.modules.queue.adapters.db.live_queue_validation import require_active_workload
from request_engine.modules.queue.application.errors import (
    QueueEntryNotClassifiable,
    QueueEntryRevisionConflict,
)
from request_engine.modules.queue.application.live_commands import ClassifyExpectedWorkloadCommand
from request_engine.modules.queue.contracts.live_queue import LiveQueueEntry
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)


async def classify_expected_workload(
    session_factory: SessionFactory,
    command: ClassifyExpectedWorkloadCommand,
) -> LiveQueueEntry:
    fingerprint = command_fingerprint(
        "queue.classify_expected_workload",
        {
            "queue_entry_id": command.queue_entry_id,
            "expected_revision": command.expected_revision,
            "expected_workload_classification_id": command.expected_workload_classification_id,
        },
    )
    async with tenant_transaction(session_factory, command.organization_id) as session:
        idem, replay = await acquire_idempotency(
            session,
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            capability="queue.classify_expected_workload",
            idempotency_key=command.idempotency_key,
            fingerprint=fingerprint,
        )
        if replay is not None:
            return entry_from_json(cast(dict[str, object], replay["entry"]))
        probe = await probe_queue_entry(session, command.organization_id, command.queue_entry_id)
        if probe is None:
            raise QueueEntryNotClassifiable(command.queue_entry_id, "missing")
        await lock_active_queue(
            session,
            command.organization_id,
            cast(UUID, probe["service_queue_id"]),
        )
        row = await lock_queue_entry(session, command.organization_id, command.queue_entry_id)
        actual_revision = cast(int, row["revision"])
        if actual_revision != command.expected_revision:
            raise QueueEntryRevisionConflict(
                command.queue_entry_id,
                command.expected_revision,
                actual_revision,
            )
        current_status = cast(str, row["status"])
        if current_status not in {"waiting", "called"}:
            raise QueueEntryNotClassifiable(command.queue_entry_id, current_status)
        await require_active_workload(
            session,
            command.organization_id,
            command.expected_workload_classification_id,
        )
        current_workload = cast(UUID | None, row["expected_workload_classification_id"])
        if current_workload == command.expected_workload_classification_id:
            result = entry_from_row(row)
        else:
            updated = await session.execute(
                text(
                    "UPDATE request_engine.queue_entries "
                    "SET expected_workload_classification_id=:workload_id,"
                    "revision=revision+1,updated_at=clock_timestamp() "
                    "WHERE organization_id=:organization_id AND id=:entry_id "
                    "RETURNING id,service_queue_id,subject_party_id,reservation_id,offering_id,"
                    "status,arrived_at,admitted_at,called_at,"
                    "expected_workload_classification_id,revision"
                ),
                {
                    "organization_id": command.organization_id,
                    "entry_id": command.queue_entry_id,
                    "workload_id": command.expected_workload_classification_id,
                },
            )
            result = entry_from_row(updated.mappings().one())
            payload = {
                "queue_entry_id": str(result.id),
                "queue_id": str(result.queue_id),
                "expected_workload_classification_id": (
                    str(result.expected_workload_classification_id)
                    if result.expected_workload_classification_id
                    else None
                ),
                "revision": result.revision,
            }
            await record_queue_fact(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                idempotency_id=idem,
                command_name="queue.classify_expected_workload",
                aggregate_id=result.id,
                event_type="queue.entry_expected_workload_classified.v1",
                details=payload,
                payload=payload,
            )
        await complete_idempotency(session, idem, {"entry": entry_to_json(result)})
        return result
