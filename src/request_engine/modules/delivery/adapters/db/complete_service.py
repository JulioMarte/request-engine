from typing import cast

from sqlalchemy import text

from request_engine.modules.delivery.adapters.db.live_common import (
    db_now,
    require_revision,
    require_workload,
)
from request_engine.modules.delivery.adapters.db.live_recording import record_live_fact
from request_engine.modules.delivery.adapters.db.live_serialization import (
    session_from_json,
    session_from_row,
    session_to_json,
)
from request_engine.modules.delivery.adapters.db.live_session_lock import lock_session_context
from request_engine.modules.delivery.application.errors import ServiceSessionNotActionable
from request_engine.modules.delivery.application.service_session_commands import (
    CompleteServiceCommand,
)
from request_engine.modules.delivery.contracts.service_session import ServiceSession
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)


async def complete_service(
    session_factory: SessionFactory,
    command: CompleteServiceCommand,
) -> ServiceSession:
    fingerprint = command_fingerprint(
        "service_session.complete",
        {
            "service_session_id": command.service_session_id,
            "expected_revision": command.expected_revision,
            "actual_workload_classification_id": command.actual_workload_classification_id,
        },
    )
    async with tenant_transaction(session_factory, command.organization_id) as session:
        idem, replay = await acquire_idempotency(
            session,
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            capability="service_session.complete",
            idempotency_key=command.idempotency_key,
            fingerprint=fingerprint,
        )
        if replay is not None:
            return session_from_json(cast(dict[str, object], replay["session"]))
        entry, locked = await lock_session_context(
            session,
            command.organization_id,
            command.service_session_id,
        )
        require_revision(locked, command.service_session_id, command.expected_revision)
        current = cast(str, locked["status"])
        if current != "active" or entry["status"] != "serving":
            raise ServiceSessionNotActionable(command.service_session_id, current, "complete")
        await require_workload(
            session,
            command.organization_id,
            command.actual_workload_classification_id,
        )
        completed_at = await db_now(session)
        result_row = await session.execute(
            text(
                "UPDATE request_engine.service_sessions SET status='completed', "
                "completed_at=:completed_at, "
                "actual_workload_classification_id=COALESCE("
                ":workload_id,actual_workload_classification_id), revision=revision+1, "
                "updated_at=clock_timestamp() "
                "WHERE organization_id=:organization_id AND id=:session_id "
                "RETURNING id,queue_entry_id,resource_id,location_id,"
                "actual_workload_classification_id,status,started_at,completed_at,revision"
            ),
            {
                "organization_id": command.organization_id,
                "session_id": command.service_session_id,
                "completed_at": completed_at,
                "workload_id": command.actual_workload_classification_id,
            },
        )
        result = session_from_row(result_row.mappings().one())
        await session.execute(
            text(
                "SELECT request_cmd.mark_queue_entry_service_completed("
                ":organization_id, :entry_id, :completed_at)"
            ),
            {
                "organization_id": command.organization_id,
                "entry_id": result.queue_entry_id,
                "completed_at": completed_at,
            },
        )
        payload = session_to_json(result)
        await record_live_fact(
            session,
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            idempotency_id=idem,
            command_name="service_session.complete",
            aggregate_kind="ServiceSession",
            aggregate_id=result.id,
            event_type="service_session.completed.v1",
            payload=payload,
        )
        await complete_idempotency(session, idem, {"session": payload})
        return result
