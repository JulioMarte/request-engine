from typing import cast

from sqlalchemy import text

from request_engine.modules.delivery.adapters.db.live_common import db_now, lock_resource
from request_engine.modules.delivery.adapters.db.live_recording import record_live_fact
from request_engine.modules.delivery.adapters.db.live_serialization import (
    activity_from_json,
    activity_from_row,
    activity_to_json,
)
from request_engine.modules.delivery.adapters.db.live_session_lock import (
    require_execution_assignment,
)
from request_engine.modules.delivery.application.resource_activity_commands import (
    StartResourceActivityCommand,
)
from request_engine.modules.delivery.contracts.service_session import ResourceActivity
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)


async def start_resource_activity(
    session_factory: SessionFactory,
    command: StartResourceActivityCommand,
) -> ResourceActivity:
    fingerprint = command_fingerprint(
        "resource_activity.start",
        {
            "resource_id": command.resource_id,
            "location_id": command.location_id,
            "kind": command.kind.value,
        },
    )
    async with tenant_transaction(session_factory, command.organization_id) as session:
        idem, replay = await acquire_idempotency(
            session,
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            capability="resource_activity.start",
            idempotency_key=command.idempotency_key,
            fingerprint=fingerprint,
        )
        if replay is not None:
            return activity_from_json(cast(dict[str, object], replay["activity"]))
        await lock_resource(session, command.organization_id, command.resource_id)
        started_at = await db_now(session)
        if command.location_id is not None:
            await require_execution_assignment(
                session,
                organization_id=command.organization_id,
                resource_id=command.resource_id,
                location_id=command.location_id,
                at=started_at,
            )
        row = await session.execute(
            text(
                "INSERT INTO request_engine.resource_activities "
                "(organization_id,resource_id,location_id,activity_kind,started_at,"
                "started_by_principal_id) VALUES "
                "(:organization_id,:resource_id,:location_id,:kind,:started_at,:principal_id) "
                "RETURNING id,resource_id,location_id,activity_kind,"
                "started_at,ended_at,revision"
            ),
            {
                "organization_id": command.organization_id,
                "resource_id": command.resource_id,
                "location_id": command.location_id,
                "kind": command.kind.value,
                "started_at": started_at,
                "principal_id": command.principal_id,
            },
        )
        result = activity_from_row(row.mappings().one())
        payload = activity_to_json(result)
        await record_live_fact(
            session,
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            idempotency_id=idem,
            command_name="resource_activity.start",
            aggregate_kind="ResourceActivity",
            aggregate_id=result.id,
            event_type="resource_activity.started.v1",
            payload=payload,
        )
        await complete_idempotency(session, idem, {"activity": payload})
        return result
