from typing import cast
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.delivery.adapters.db.live_common import (
    db_now,
    lock_queue,
    lock_queue_entry,
    lock_resource,
    probe_queue_entry,
    require_revision,
    require_workload,
)
from request_engine.modules.delivery.adapters.db.live_recording import record_live_fact
from request_engine.modules.delivery.adapters.db.live_serialization import (
    session_from_json,
    session_to_json,
)
from request_engine.modules.delivery.adapters.db.live_session_lock import (
    require_execution_assignment,
)
from request_engine.modules.delivery.adapters.db.start_service_persistence import (
    insert_service_session,
)
from request_engine.modules.delivery.application.errors import QueueEntryNotCallable
from request_engine.modules.delivery.application.service_session_commands import StartServiceCommand
from request_engine.modules.delivery.contracts.service_session import ServiceSession
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)


async def start_service(
    session_factory: SessionFactory,
    command: StartServiceCommand,
) -> ServiceSession:
    fingerprint = command_fingerprint(
        "service_session.start",
        {
            "queue_entry_id": command.queue_entry_id,
            "resource_id": command.resource_id,
            "location_id": command.location_id,
            "expected_queue_revision": command.expected_queue_revision,
            "actual_workload_classification_id": command.actual_workload_classification_id,
        },
    )
    async with tenant_transaction(session_factory, command.organization_id) as session:
        idem, replay = await acquire_idempotency(
            session,
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            capability="service_session.start",
            idempotency_key=command.idempotency_key,
            fingerprint=fingerprint,
        )
        if replay is not None:
            return session_from_json(cast(dict[str, object], replay["session"]))
        probe = await probe_queue_entry(
            session,
            command.organization_id,
            command.queue_entry_id,
        )
        await lock_queue(
            session,
            command.organization_id,
            cast(UUID, probe["service_queue_id"]),
        )
        entry = await lock_queue_entry(
            session,
            command.organization_id,
            command.queue_entry_id,
        )
        require_revision(entry, command.queue_entry_id, command.expected_queue_revision)
        if entry["status"] != "called":
            raise QueueEntryNotCallable(
                command.queue_entry_id,
                cast(str, entry["status"]),
            )
        await lock_resource(session, command.organization_id, command.resource_id)
        started_at = await db_now(session)
        await require_execution_assignment(
            session,
            organization_id=command.organization_id,
            resource_id=command.resource_id,
            location_id=command.location_id,
            at=started_at,
        )
        await require_workload(
            session,
            command.organization_id,
            command.actual_workload_classification_id,
        )
        result = await insert_service_session(session, command, started_at)
        await session.execute(
            text(
                "SELECT request_cmd.mark_queue_entry_service_started("
                ":organization_id, :entry_id, :started_at)"
            ),
            {
                "organization_id": command.organization_id,
                "entry_id": command.queue_entry_id,
                "started_at": result.started_at,
            },
        )
        payload = session_to_json(result)
        await record_live_fact(
            session,
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            idempotency_id=idem,
            command_name="service_session.start",
            aggregate_kind="ServiceSession",
            aggregate_id=result.id,
            event_type="service_session.started.v1",
            payload=payload,
        )
        await complete_idempotency(session, idem, {"session": payload})
        return result
