import asyncio
from collections.abc import Mapping
from datetime import datetime, time
from typing import LiteralString
from uuid import uuid4

import pytest
from httpx import AsyncClient, Response

from request_engine.platform.db.session import SessionFactory

from .f4_capacity_support import seed_today_schedule
from .f4_operational_day_support import configure_projection
from .f5_booking_fixture import five_minute_sandbox
from .f5_contextual_support import contextualize_recovery_supply, restrict_contextual_capacity
from .f5_extend_day_fixture import close_location_after_slots, grant_extend_day_authority
from .f5_extend_day_support import (
    assignment_recovery_exception_count,
    owner_revisions,
    source_revision,
)
from .f5_recovery_assertions import create_proposal
from .f5_recovery_support import book_commitments, restrict_source_to_first_six
from .f5_replace_resource_support import seed_incident_for_proposal
from .f6_copilot_support import copilot_actor, read_tool
from .f6_roadmap_support import local_noon_timezone as noon
from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox, auth, client_with_actors, seed_tenant_sandbox
from .world_clock import location_timezone

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.contract,
    pytest.mark.adversarial,
]


def _sandbox(conn: PgConnection, name: str) -> TenantSandbox:
    return five_minute_sandbox(conn, seed_tenant_sandbox(conn, name))


def _single(conn: PgConnection, sql: LiteralString, params: tuple[object, ...]) -> None:
    row = conn.execute(sql, params).fetchone()
    assert row is not None and row[0] == 1


async def _concurrent_posts(
    client: AsyncClient, sandbox: TenantSandbox, path: str, body: Mapping[str, object]
) -> tuple[Response, Response]:
    headers = auth(sandbox, idempotency_key=f"f6-conc-{uuid4().hex}")
    url = f"/v1/operational-copilot/tools{path}"
    first, second = await asyncio.gather(
        client.post(url, json=body, headers=headers),
        client.post(url, json=body, headers=headers),
    )
    assert first.status_code == 200 and second.status_code == 200, (first.text, second.text)
    assert first.json()["result_id"] == second.json()["result_id"]
    return first, second


async def test_f6_concurrent_recovery_proposal_and_execution_replay_once(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = _sandbox(e2e_admin_conn, "f6-matrix-recovery")
    seed_today_schedule(e2e_admin_conn, sandbox)
    actors = {sandbox.token: copilot_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        await configure_projection(client, sandbox)
        _, slots = await book_commitments(client, e2e_admin_conn, sandbox)
        restrict_source_to_first_six(e2e_admin_conn, sandbox, slots)
        pbody = {"service_queue_id": str(sandbox.queue_id), "search_days": 7}
        pfirst, _ = await _concurrent_posts(client, sandbox, "/recovery/proposals", pbody)
        at_risk = await read_tool(
            client, sandbox, f"/queues/{sandbox.queue_id}/at-risk-reservations"
        )
        ebody = {
            "proposal_id": pfirst.json()["result_id"],
            "reservation_id": at_risk["affected"][0]["reservation_id"],
            "notify": True,
        }
        await _concurrent_posts(client, sandbox, "/recovery/executions", ebody)
    row = e2e_admin_conn.execute(
        "SELECT (SELECT count(*) FROM request_engine.operational_recovery_proposals"
        " WHERE organization_id=%s AND service_queue_id=%s),"
        " (SELECT count(*) FROM request_engine.operational_recovery_executions"
        " WHERE organization_id=%s)",
        (sandbox.organization_id, sandbox.queue_id, sandbox.organization_id),
    ).fetchone()
    assert row is not None and row[0] == 1 and row[1] == 1


async def test_f6_concurrent_recovery_day_extension_replays_once(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = _sandbox(e2e_admin_conn, "f6-matrix-extend")
    grant_extend_day_authority(e2e_admin_conn, sandbox)
    seed_today_schedule(e2e_admin_conn, sandbox, business_timezone=noon(e2e_admin_conn))
    supply = contextualize_recovery_supply(e2e_admin_conn, sandbox)
    actors = {sandbox.token: copilot_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        await configure_projection(client, sandbox)
        _, slots = await book_commitments(client, e2e_admin_conn, sandbox)
        restrict_contextual_capacity(e2e_admin_conn, sandbox, supply, slots, count=6)
        close_location_after_slots(e2e_admin_conn, sandbox, slots, count=6)
        proposal = await create_proposal(client, sandbox)
        incident_id = seed_incident_for_proposal(e2e_admin_conn, sandbox, proposal)
        operational_revision, availability_revision = owner_revisions(e2e_admin_conn, sandbox)
        zone = location_timezone(e2e_admin_conn, sandbox)
        day_end = datetime.fromisoformat(slots[5]["end_at"]).astimezone(zone)
        body = {
            "incident_id": str(incident_id),
            "assignment_id": str(supply.assignment_id),
            "start_at": day_end.isoformat(),
            "end_at": datetime.combine(day_end.date(), time(19), tzinfo=zone).isoformat(),
            "expected_source_revision": source_revision(proposal),
            "expected_location_operational_revision": operational_revision,
            "expected_resource_availability_revision": availability_revision,
            "reason": "concurrent recovery day extension",
        }
        await _concurrent_posts(client, sandbox, "/recovery/day-extensions", body)
    _single(
        e2e_admin_conn,
        "SELECT count(*) FROM request_engine.operational_recovery_actions "
        "WHERE organization_id=%s AND incident_id=%s AND action_kind='extend_day'",
        (sandbox.organization_id, incident_id),
    )
    assert assignment_recovery_exception_count(e2e_admin_conn, sandbox, supply.assignment_id) == 1
