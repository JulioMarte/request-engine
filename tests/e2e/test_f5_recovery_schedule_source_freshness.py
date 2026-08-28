from __future__ import annotations

from typing import cast

import pytest

from request_engine.platform.db.session import SessionFactory

from .f4_operational_day_support import configure_projection
from .f5_contextual_support import contextualize_recovery_supply
from .f5_recovery_support import f5_actor
from .operational_support import PgConnection
from .tenant_sandbox import client_with_actors, seed_tenant_sandbox

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.contract,
    pytest.mark.invariant,
    pytest.mark.provenance,
]


def _source_revision(conn: PgConnection, organization_id: object, queue_id: object) -> int:
    row = conn.execute(
        "SELECT revision FROM request_engine.recovery_source_revisions "
        "WHERE organization_id=%s AND service_queue_id=%s",
        (organization_id, queue_id),
    ).fetchone()
    assert row is not None
    return cast(int, row[0])


def _scheduled_revision(
    conn: PgConnection,
    organization_id: object,
    queue_id: object,
    revision: int,
) -> tuple[object, ...] | None:
    return conn.execute(
        "SELECT owner_module,action_type,subject_kind,subject_id,"
        "payload->>'source_revision' FROM request_engine.scheduled_actions "
        "WHERE organization_id=%s AND dedupe_key=%s",
        (organization_id, f"f5-reassessment:{queue_id}:{revision}"),
    ).fetchone()


async def test_f1_schedule_changes_advance_and_schedule_f5_source_once(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "f5-schedule-source-freshness")
    actors = {sandbox.token: f5_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        await configure_projection(client, sandbox)

    supply = contextualize_recovery_supply(e2e_admin_conn, sandbox)
    before_location = _source_revision(e2e_admin_conn, sandbox.organization_id, sandbox.queue_id)
    e2e_admin_conn.execute(
        "INSERT INTO request_engine.location_hours_exceptions "
        "(organization_id,location_id,during,exception_kind,reason,active) "
        "VALUES (%s,%s,tstzrange(clock_timestamp() + interval '2 hours',"
        "clock_timestamp() + interval '3 hours','[)'),'available','f5 freshness proof',true)",
        (sandbox.organization_id, sandbox.location_id),
    )
    after_location = _source_revision(e2e_admin_conn, sandbox.organization_id, sandbox.queue_id)
    assert after_location == before_location + 1
    assert _scheduled_revision(
        e2e_admin_conn, sandbox.organization_id, sandbox.queue_id, after_location
    ) == (
        "operational_recovery",
        "reassess_recovery_scope",
        "ServiceQueue",
        sandbox.queue_id,
        str(after_location),
    )

    e2e_admin_conn.execute(
        "INSERT INTO request_engine.resource_location_schedule_exceptions "
        "(organization_id,resource_location_assignment_id,during,exception_kind,reason,active) "
        "VALUES (%s,%s,tstzrange(clock_timestamp() + interval '4 hours',"
        "clock_timestamp() + interval '5 hours','[)'),'available','f5 freshness proof',true)",
        (sandbox.organization_id, supply.assignment_id),
    )
    after_assignment = _source_revision(e2e_admin_conn, sandbox.organization_id, sandbox.queue_id)
    assert after_assignment == after_location + 1
    assert _scheduled_revision(
        e2e_admin_conn, sandbox.organization_id, sandbox.queue_id, after_assignment
    ) == (
        "operational_recovery",
        "reassess_recovery_scope",
        "ServiceQueue",
        sandbox.queue_id,
        str(after_assignment),
    )
