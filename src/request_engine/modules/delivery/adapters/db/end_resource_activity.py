from typing import cast
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.delivery.adapters.db.live_common import (
    db_now,
    lock_resource,
    require_revision,
)
from request_engine.modules.delivery.adapters.db.live_recording import record_live_fact
from request_engine.modules.delivery.adapters.db.live_serialization import (
    activity_from_json,
    activity_from_row,
    activity_to_json,
)
from request_engine.modules.delivery.application.errors import ResourceActivityNotFound
from request_engine.modules.delivery.application.resource_activity_commands import (
    EndResourceActivityCommand,
)
from request_engine.modules.delivery.contracts.service_session import ResourceActivity
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)


async def end_resource_activity(
    session_factory: SessionFactory,
    command: EndResourceActivityCommand,
) -> ResourceActivity:
    fingerprint = command_fingerprint(
        "resource_activity.end",
        {
            "resource_activity_id": command.resource_activity_id,
            "expected_revision": command.expected_revision,
        },
    )
    async with tenant_transaction(session_factory, command.organization_id) as session:
        idem, replay = await acquire_idempotency(
            session,
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            capability="resource_activity.end",
            idempotency_key=command.idempotency_key,
            fingerprint=fingerprint,
        )
        if replay is not None:
            return activity_from_json(cast(dict[str, object], replay["activity"]))
        probe = (
            await session.execute(
                text(
                    "SELECT resource_id FROM request_engine.resource_activities "
                    "WHERE organization_id=:organization_id AND id=:activity_id"
                ),
                {
                    "organization_id": command.organization_id,
                    "activity_id": command.resource_activity_id,
                },
            )
        ).first()
        if probe is None:
            raise ResourceActivityNotFound(command.resource_activity_id)
        await lock_resource(session, command.organization_id, cast(UUID, probe[0]))
        row = (
            (
                await session.execute(
                    text(
                        "SELECT id,resource_id,location_id,activity_kind,started_at,"
                        "ended_at,revision FROM request_engine.resource_activities "
                        "WHERE organization_id=:organization_id "
                        "AND id=:activity_id FOR UPDATE"
                    ),
                    {
                        "organization_id": command.organization_id,
                        "activity_id": command.resource_activity_id,
                    },
                )
            )
            .mappings()
            .one()
        )
        require_revision(row, command.resource_activity_id, command.expected_revision)
        if row["ended_at"] is not None:
            raise ResourceActivityNotFound(command.resource_activity_id)
        ended_at = await db_now(session)
        updated = (
            (
                await session.execute(
                    text(
                        "UPDATE request_engine.resource_activities SET ended_at=:ended_at, "
                        "ended_by_principal_id=:principal_id, revision=revision+1 "
                        "WHERE organization_id=:organization_id AND id=:activity_id "
                        "RETURNING id,resource_id,location_id,activity_kind,"
                        "started_at,ended_at,revision"
                    ),
                    {
                        "organization_id": command.organization_id,
                        "activity_id": command.resource_activity_id,
                        "ended_at": ended_at,
                        "principal_id": command.principal_id,
                    },
                )
            )
            .mappings()
            .one()
        )
        result = activity_from_row(updated)
        payload = activity_to_json(result)
        await record_live_fact(
            session,
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            idempotency_id=idem,
            command_name="resource_activity.end",
            aggregate_kind="ResourceActivity",
            aggregate_id=result.id,
            event_type="resource_activity.ended.v1",
            payload=payload,
        )
        await complete_idempotency(session, idem, {"activity": payload})
        return result
