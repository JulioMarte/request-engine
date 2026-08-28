from __future__ import annotations

from datetime import datetime
from typing import Any, cast
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from request_engine.platform.db.session import SessionFactory

from .f4_capacity_support import seed_today_schedule
from .f4_operational_day_support import configure_projection
from .f5_booking_fixture import five_minute_sandbox
from .f5_contextual_support import contextualize_recovery_supply, restrict_contextual_capacity
from .f5_extend_day_support import (
    assignment_recovery_exception_count,
    location_recovery_exception_count,
    owner_revisions,
    source_revision,
)
from .f5_recovery_assertions import create_proposal
from .f5_recovery_support import book_commitments, f5_actor
from .f5_replace_resource_support import seed_incident_for_proposal
from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox, auth, client_with_actors, seed_tenant_sandbox

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.contract,
    pytest.mark.invariant,
    pytest.mark.provenance,
]

_TZ = ZoneInfo("America/Santo_Domingo")


def _grant_extend_day_authority(conn: PgConnection, sandbox: TenantSandbox) -> None:
    for scope in ("operations.manage_profile", "operations.manage_supply"):
        conn.execute(
            "INSERT INTO request_engine.representations "
            "(organization_id,principal_id,represented_party_id,authority_kind,"
            "scope_key,valid_until) "
            "VALUES (%s,%s,%s,'delegated',%s,clock_timestamp() + interval '1 day')",
            (sandbox.organization_id, sandbox.principal_id, sandbox.party_id, scope),
        )


def _close_location_after_slots(
    conn: PgConnection,
    sandbox: TenantSandbox,
    slots: list[dict[str, Any]],
    *,
    count: int,
) -> None:
    start = datetime.fromisoformat(cast(str, slots[0]["start_at"])).astimezone(_TZ)
    end = datetime.fromisoformat(cast(str, slots[count - 1]["end_at"])).astimezone(_TZ)
    conn.execute(
        "DELETE FROM request_engine.location_operational_hours "
        "WHERE organization_id=%s AND location_id=%s AND weekday=%s",
        (sandbox.organization_id, sandbox.location_id, start.weekday()),
    )
    conn.execute(
        "INSERT INTO request_engine.location_operational_hours "
        "(organization_id,location_id,weekday,local_start,local_end) "
        "VALUES (%s,%s,%s,%s,%s)",
        (
            sandbox.organization_id,
            sandbox.location_id,
            start.weekday(),
            start.timetz().replace(tzinfo=None),
            end.timetz().replace(tzinfo=None),
        ),
    )


def _recurring_schedule_snapshot(
    conn: PgConnection,
    sandbox: TenantSandbox,
    assignment_id: object,
) -> tuple[list[tuple[object, ...]], list[tuple[object, ...]]]:
    location_rows = conn.execute(
        "SELECT weekday,local_start,local_end FROM request_engine.location_operational_hours "
        "WHERE organization_id=%s AND location_id=%s ORDER BY weekday,local_start",
        (sandbox.organization_id, sandbox.location_id),
    ).fetchall()
    assignment_rows = conn.execute(
        "SELECT weekday,local_start,local_end "
        "FROM request_engine.resource_location_availability "
        "WHERE organization_id=%s AND resource_location_assignment_id=%s "
        "ORDER BY weekday,local_start",
        (sandbox.organization_id, assignment_id),
    ).fetchall()
    return ([tuple(row) for row in location_rows], [tuple(row) for row in assignment_rows])


async def test_f5_extend_day_clears_closing_shortfall_without_rewriting_recurring_schedules(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    base = seed_tenant_sandbox(e2e_admin_conn, "f5-extend-day-success")
    sandbox = five_minute_sandbox(e2e_admin_conn, base)
    _grant_extend_day_authority(e2e_admin_conn, sandbox)
    seed_today_schedule(e2e_admin_conn, sandbox)
    supply = contextualize_recovery_supply(e2e_admin_conn, sandbox)
    actors = {sandbox.token: f5_actor(sandbox)}

    async with client_with_actors(e2e_session_factory, actors) as client:
        await configure_projection(client, sandbox)
        _, slots = await book_commitments(client, e2e_admin_conn, sandbox)
        restrict_contextual_capacity(e2e_admin_conn, sandbox, supply, slots, count=6)
        _close_location_after_slots(e2e_admin_conn, sandbox, slots, count=6)
        proposal = await create_proposal(client, sandbox)
        assert proposal["scheduled_shortfall_seconds"] > 0
        incident_id = seed_incident_for_proposal(e2e_admin_conn, sandbox, proposal)
        expected_source_revision = source_revision(proposal)
        location_revision, resource_revision = owner_revisions(e2e_admin_conn, sandbox)
        recurring_before = _recurring_schedule_snapshot(
            e2e_admin_conn, sandbox, supply.assignment_id
        )
        location_exceptions_before = location_recovery_exception_count(
            e2e_admin_conn, sandbox
        )
        assignment_exceptions_before = assignment_recovery_exception_count(
            e2e_admin_conn, sandbox, supply.assignment_id
        )

        start_at = datetime.fromisoformat(cast(str, slots[6]["start_at"]))
        end_at = datetime.fromisoformat(cast(str, slots[9]["end_at"]))
        response = await client.post(
            f"/v1/operational-recovery/incidents/{incident_id}/extend-day",
            json={
                "expected_source_revision": expected_source_revision,
                "authority_party_id": str(sandbox.party_id),
                "assignment_id": str(supply.assignment_id),
                "start_at": start_at.isoformat(),
                "end_at": end_at.isoformat(),
                "expected_location_operational_revision": location_revision,
                "expected_resource_availability_revision": resource_revision,
                "reason": "recover commitments beyond closing time",
            },
            headers=auth(sandbox, idempotency_key=f"f5-extend-day-{uuid4().hex}"),
        )

    assert response.status_code == 200, response.text
    action = response.json()
    assert action["status"] == "succeeded"
    reassessment = cast(dict[str, object], action["owner_steps"])["reassessment"]
    reassessment = cast(dict[str, object], reassessment)
    assert reassessment["scheduled_shortfall_seconds"] == 0
    assert reassessment["incident_status"] == "resolved"
    assert location_recovery_exception_count(e2e_admin_conn, sandbox) == (
        location_exceptions_before + 1
    )
    assert assignment_recovery_exception_count(
        e2e_admin_conn, sandbox, supply.assignment_id
    ) == (assignment_exceptions_before + 1)
    assert _recurring_schedule_snapshot(
        e2e_admin_conn, sandbox, supply.assignment_id
    ) == recurring_before
