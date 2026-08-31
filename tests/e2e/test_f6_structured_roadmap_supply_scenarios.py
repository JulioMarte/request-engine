from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from .f4_operational_day_support import configure_projection
from .f5_booking_fixture import five_minute_sandbox
from .f5_recovery_support import book_commitments, restrict_source_to_first_six
from .f6_copilot_support import copilot_actor, execute_tool, read_tool
from .f6_roadmap_support import (
    seed_named_resource_day_schedule,
    seed_publishable_discovery_world,
)
from .operational_support import PgConnection
from .tenant_sandbox import client_with_actors, seed_tenant_sandbox

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e, pytest.mark.postgres, pytest.mark.contract]


async def test_roadmap_publish_discovery_satisfied_by_structured_tools(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "f6-scenario-discovery")
    seed_named_resource_day_schedule(e2e_admin_conn, sandbox, display_name="Dr. B")
    seed_publishable_discovery_world(e2e_admin_conn, sandbox)
    actors = {sandbox.token: copilot_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        offering = (
            await read_tool(client, sandbox, f"/offerings?reference={sandbox.offering_key}")
        )[0]
        resource = (await read_tool(client, sandbox, "/resources?reference=Dr.%20B"))[0]
        body = {
            "offering_id": str(offering["offering_id"]),
            "location_id": str(resource["location_id"]),
            "resource_id": str(resource["resource_id"]),
            "effective_start": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
            "provider_visibility": "public",
        }
        receipt = await execute_tool(
            client, sandbox, "/discovery/publications", body, f"f6-scenario-publish-{uuid4().hex}"
        )
        publication = await read_tool(
            client,
            sandbox,
            f"/discovery/publications/{receipt['result_id']}",
        )
    assert receipt["action"] == "publish_discovery_supply"
    assert publication["status"] == "active"


async def test_roadmap_at_risk_inspection_satisfied_by_structured_tools(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    base = seed_tenant_sandbox(e2e_admin_conn, "f6-scenario-at-risk")
    sandbox = five_minute_sandbox(e2e_admin_conn, base)
    seed_named_resource_day_schedule(e2e_admin_conn, sandbox, display_name="Dr. A")
    actors = {sandbox.token: copilot_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        await configure_projection(client, sandbox)
        reservations, slots = await book_commitments(client, e2e_admin_conn, sandbox)
        restrict_source_to_first_six(e2e_admin_conn, sandbox, slots)
        assessment = await read_tool(
            client,
            sandbox,
            f"/queues/{sandbox.queue_id}/at-risk-reservations",
        )
    assert len(assessment["affected"]) == len(reservations) - 6, assessment
    assert assessment["shortfall_seconds"] > 0
