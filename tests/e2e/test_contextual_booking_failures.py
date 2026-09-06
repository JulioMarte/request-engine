from __future__ import annotations

from typing import Any, cast
from uuid import uuid4

import pytest
from httpx import AsyncClient

from request_engine.platform.db.session import SessionFactory

from .contextual_supply_support import contextualize_sandbox
from .evidence import durable_snapshot
from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox, auth, client_for, first_slot, seed_tenant_sandbox


def _world(conn: PgConnection) -> TenantSandbox:
    sandbox = seed_tenant_sandbox(conn, "contextual-failure-e2e")
    contextualize_sandbox(conn, sandbox)
    return sandbox


async def _book(client: AsyncClient, sandbox: TenantSandbox, option_id: object) -> dict[str, Any]:
    response = await client.post(
        "/v1/appointments",
        json={"option_id": str(option_id), "subject_party_id": str(sandbox.party_id)},
        headers=auth(sandbox, idempotency_key=f"book-{uuid4().hex}"),
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
@pytest.mark.contract
@pytest.mark.adversarial
async def test_stale_contextual_option_is_http_409_without_partial_effects(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = _world(e2e_admin_conn)
    async with client_for(e2e_session_factory, sandbox) as client:
        slot = await first_slot(client, sandbox)
        e2e_admin_conn.execute(
            "UPDATE request_engine.booking_context_terms SET amount = 4100 "
            "WHERE organization_id = %s",
            (sandbox.organization_id,),
        )
        before = durable_snapshot(e2e_admin_conn)
        response = await client.post(
            "/v1/appointments",
            json={"option_id": slot["option_id"], "subject_party_id": str(sandbox.party_id)},
            headers=auth(sandbox, idempotency_key=f"stale-{uuid4().hex}"),
        )
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "appointment_option_stale"
    assert error["resolution"] == "refresh_and_retry"
    assert durable_snapshot(e2e_admin_conn) == before


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
@pytest.mark.contract
@pytest.mark.adversarial
async def test_contextual_reschedule_rejects_stale_revision_without_mutation(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = _world(e2e_admin_conn)
    async with client_for(e2e_session_factory, sandbox) as client:
        reservation = await _book(client, sandbox, (await first_slot(client, sandbox))["option_id"])
        replacement = await first_slot(client, sandbox)
        before = durable_snapshot(e2e_admin_conn)
        response = await client.post(
            f"/v1/appointments/{reservation['id']}/reschedule",
            json={
                "option_id": replacement["option_id"],
                "expected_revision": cast(int, reservation["revision"]) + 1,
            },
            headers=auth(sandbox, idempotency_key=f"reschedule-{uuid4().hex}"),
        )
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "revision_conflict"
    assert error["resolution"] == "refresh_and_retry"
    assert durable_snapshot(e2e_admin_conn) == before
