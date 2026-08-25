from typing import cast

from sqlalchemy import text

from request_engine.modules.delivery.adapters.db.live_common import db_now, require_revision
from request_engine.modules.delivery.adapters.db.live_recording import record_live_fact
from request_engine.modules.delivery.adapters.db.live_serialization import (
    session_from_json,
    session_from_row,
    session_to_json,
)
from request_engine.modules.delivery.adapters.db.live_session_lock import lock_session_context
from request_engine.modules.delivery.application.errors import ServiceSessionNotActionable
from request_engine.modules.delivery.application.service_session_commands import PauseServiceCommand
from request_engine.modules.delivery.contracts.service_session import ServiceSession
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)


async def pause_service(
    session_factory: SessionFactory,
    command: PauseServiceCommand,
) -> ServiceSession:
    fingerprint = command_fingerprint(
        "service_session.pause",
        {
            "service_session_id": command.service_session_id,
            "expected_revision": command.expected_revision,
            "kind": command.kind.value,
        },
    )
    async with tenant_transaction(session_factory, command.organization_id) as session:
        idem, replay = await acquire_idempotency(
            session,
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            capability="service_session.pause",
            idempotency_key=command.idempotency_key,
            fingerprint=fingerprint,
        )
        if replay is not None:
            return session_from_json(cast(dict[str, object], replay["session"]))
        _, locked = await lock_session_context(
            session,
            command.organization_id,
            command.service_session_id,
        )
        require_revision(locked, command.service_session_id, command.expected_revision)
        current = cast(str, locked["status"])
        if current != "active":
            raise ServiceSessionNotActionable(command.service_session_id, current, "pause")
        paused_at = await db_now(session)
        await session.execute(
            text(
                "INSERT INTO request_engine.service_session_interruptions "
                "(organization_id,service_session_id,kind,started_at,"
                "started_by_principal_id) VALUES "
                "(:organization_id,:session_id,:kind,:started_at,:principal_id)"
            ),
            {
                "organization_id": command.organization_id,
                "session_id": command.service_session_id,
                "kind": command.kind.value,
                "started_at": paused_at,
                "principal_id": command.principal_id,
            },
        )
        result_row = await session.execute(
            text(
                "UPDATE request_engine.service_sessions SET status='paused', "
                "revision=revision+1, updated_at=clock_timestamp() "
                "WHERE organization_id=:organization_id AND id=:session_id "
                "RETURNING id,queue_entry_id,resource_id,location_id,"
                "actual_workload_classification_id,status,started_at,completed_at,revision"
            ),
            {
                "organization_id": command.organization_id,
                "session_id": command.service_session_id,
            },
        )
        result = session_from_row(result_row.mappings().one())
        payload = {**session_to_json(result), "transitioned_at": paused_at.isoformat()}
        await record_live_fact(
            session,
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            idempotency_id=idem,
            command_name="service_session.pause",
            aggregate_kind="ServiceSession",
            aggregate_id=result.id,
            event_type="service_session.paused.v1",
            payload=payload,
        )
        await complete_idempotency(session, idem, {"session": session_to_json(result)})
        return result
