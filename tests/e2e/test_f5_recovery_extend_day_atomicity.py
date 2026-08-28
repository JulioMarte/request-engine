from __future__ import annotations

from typing import Any, cast
from uuid import uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from .f4_capacity_support import seed_today_schedule
from .f4_operational_day_support import configure_projection
from .f5_booking_fixture import five_minute_sandbox
from .f5_contextual_support import contextualize_recovery_supply
from .f5_recovery_assertions import create_proposal
from .f5_recovery_support import book_commitments, f5_actor, restrict_source_to_first_six
from .f5_replace_resource_support import seed_incident_for_proposal
from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox, auth, client_with_actors, seed_tenant_sandbox

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.contract,
    pytest.mark.adversarial,
    pytest.mark.provenance,
]


async def test_f5_extend_day_stale_resource_step_leaves_no_partial_location_extension(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    base = seed_tenant_sandbox(e2e_admin_conn, "f5-extend-day-atomicity")
    sandbox = five_minute_sandbox(e2e_admin_conn, base)
    seed_today_schedule(e2e_admin_conn, sandbox)
    supply = contextualize_recovery_supply(e2e_admin_conn, sandbox)
    actors = {sandbox.token: f5_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        await configure_projection(client, sandbox)
        _, slots = await book_commitments(client, e2e_admin_conn, sandbox)
        restrict_source_to_first_six(e2e_admin_conn, sandbox, slots)
        proposal = await create_proposal(client, sandbox)
        incident_id = seed_incident_for_proposal(e2e_admin_conn, sandbox, proposal)
        source_revision = _source_revision(proposal)
        location_revision, resource_revision = _owner_revisions(e2e_admin_conn, sandbox)
        before_location_exceptions = _location_recovery_exception_count(e2e_admin_conn, sandbox)
        before_assignment_exceptions = _assignment_recovery_exception_count(
            e2e_admin_conn, sandbox, supply.assignment_id
        )
        start_at = slots[-1][1]
        end_at = slots[-1][2]

        response = await client.post(
            f"/v1/operational-recovery/incidents/{incident_id}/extend-day",
            json={
                "expected_source_revision": source_revision,
                "assignment_id": str(supply.assignment_id),
                "start_at": start_at.isoformat(),
                "end_at": end_at.isoformat(),
                "expected_location_operational_revision": location_revision,
                "expected_resource_availability_revision": resource_revision - 1,
                "reason": "adversarial stale resource revision",
            },
            headers=auth(sandbox, idempotency_key=f"f5-extend-day-stale-{uuid4().hex}"),
        )

    assert response.status_code == 409, response.text
    assert _location_recovery_exception_count(e2e_admin_conn, sandbox) == (
        before_location_exceptions
    )
    assert (
        _assignment_recovery_exception_count(e2e_admin_conn, sandbox, supply.assignment_id)
        == before_assignment_exceptions
    )
    assert _owner_revisions(e2e_admin_conn, sandbox) == (
        location_revision,
        resource_revision,
    )


def _source_revision(proposal: dict[str, Any]) -> int:
    checkpoint = cast(dict[str, Any], proposal["source_checkpoint"])
    return cast(int, checkpoint["recovery_source_revision"])


def _owner_revisions(conn: PgConnection, sandbox: TenantSandbox) -> tuple[int, int]:
    row = conn.execute(
        "SELECT l.operational_revision,r.availability_revision "
        "FROM request_engine.locations l "
        "JOIN request_engine.resources r ON r.organization_id=l.organization_id "
        "WHERE l.organization_id=%s AND l.id=%s AND r.id=%s",
        (sandbox.organization_id, sandbox.location_id, sandbox.resource_id),
    ).fetchone()
    assert row is not None
    return cast(tuple[int, int], tuple(row))


def _location_recovery_exception_count(conn: PgConnection, sandbox: TenantSandbox) -> int:
    row = conn.execute(
        "SELECT count(*) FROM request_engine.location_hours_exceptions "
        "WHERE organization_id=%s AND location_id=%s AND recovery_action_id IS NOT NULL",
        (sandbox.organization_id, sandbox.location_id),
    ).fetchone()
    assert row is not None
    return cast(int, row[0])


def _assignment_recovery_exception_count(
    conn: PgConnection, sandbox: TenantSandbox, assignment_id: object
) -> int:
    row = conn.execute(
        "SELECT count(*) FROM request_engine.resource_location_schedule_exceptions "
        "WHERE organization_id=%s AND resource_location_assignment_id=%s "
        "AND recovery_action_id IS NOT NULL",
        (sandbox.organization_id, assignment_id),
    ).fetchone()
    assert row is not None
    return cast(int, row[0])
