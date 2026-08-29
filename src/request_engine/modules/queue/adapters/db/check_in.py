from typing import cast
from uuid import UUID

from request_engine.modules.queue.adapters.db.check_in_persistence import (
    ensure_subject_not_active,
    insert_queue_entry,
)
from request_engine.modules.queue.adapters.db.intake_control_store import (
    require_queue_accepting_intake,
)
from request_engine.modules.queue.adapters.db.live_queue_locking import lock_active_queue
from request_engine.modules.queue.adapters.db.live_queue_recording import record_queue_fact
from request_engine.modules.queue.adapters.db.live_queue_serialization import (
    entry_from_json,
    entry_from_row,
    entry_to_json,
)
from request_engine.modules.queue.adapters.db.live_queue_validation import (
    require_active_subject,
    require_active_workload,
    require_offering,
    require_reservation_match,
)
from request_engine.modules.queue.application.errors import TenantReferenceNotUsable
from request_engine.modules.queue.application.live_commands import CheckInCommand
from request_engine.modules.queue.contracts.live_queue import LiveQueueEntry
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)


async def check_in(
    session_factory: SessionFactory,
    command: CheckInCommand,
) -> LiveQueueEntry:
    fingerprint = command_fingerprint(
        "queue.check_in",
        {
            "queue_id": command.queue_id,
            "subject_party_id": command.subject_party_id,
            "reservation_id": command.reservation_id,
            "offering_id": command.offering_id,
            "expected_workload_classification_id": (command.expected_workload_classification_id),
        },
    )
    async with tenant_transaction(session_factory, command.organization_id) as session:
        idem, replay = await acquire_idempotency(
            session,
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            capability="queue.check_in",
            idempotency_key=command.idempotency_key,
            fingerprint=fingerprint,
        )
        if replay is not None:
            return entry_from_json(cast(dict[str, object], replay["entry"]))
        queue = await lock_active_queue(session, command.organization_id, command.queue_id)
        # The intake-control row is locked in the same authoritative admission
        # transaction. A concurrent STOP_INTAKE therefore serializes with check-in:
        # either an admission commits before the stop, or the stop commits first
        # and this transaction fails closed without creating a QueueEntry.
        await require_queue_accepting_intake(
            session,
            organization_id=command.organization_id,
            service_queue_id=command.queue_id,
        )
        await require_active_subject(session, command.organization_id, command.subject_party_id)
        await require_active_workload(
            session,
            command.organization_id,
            command.expected_workload_classification_id,
        )
        offering_id = command.offering_id or cast(UUID | None, queue["offering_id"])
        if command.reservation_id is not None:
            reservation_offering = await require_reservation_match(
                session,
                organization_id=command.organization_id,
                reservation_id=command.reservation_id,
                subject_party_id=command.subject_party_id,
                queue_location_id=cast(UUID | None, queue["location_id"]),
                queue_offering_id=cast(UUID | None, queue["offering_id"]),
            )
            if offering_id is None:
                offering_id = reservation_offering
            elif offering_id != reservation_offering:
                raise TenantReferenceNotUsable("offering_id", offering_id)
        elif offering_id is not None:
            await require_offering(session, command.organization_id, offering_id)
        await ensure_subject_not_active(session, command)
        result = entry_from_row(await insert_queue_entry(session, command, offering_id))
        details: dict[str, object] = {
            "queue_id": str(command.queue_id),
            "subject_party_id": str(command.subject_party_id),
            "reservation_id": str(command.reservation_id) if command.reservation_id else None,
            "admission_kind": "reservation" if command.reservation_id else "walk_in",
        }
        await record_queue_fact(
            session,
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            idempotency_id=idem,
            command_name="queue.check_in",
            aggregate_id=result.id,
            event_type="queue.entry_checked_in.v1",
            details=details,
            payload={
                **details,
                "queue_entry_id": str(result.id),
                "arrived_at": result.arrived_at.isoformat(),
            },
        )
        await complete_idempotency(session, idem, {"entry": entry_to_json(result)})
        return result
