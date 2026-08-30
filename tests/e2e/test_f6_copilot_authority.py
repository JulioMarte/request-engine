from __future__ import annotations

from uuid import uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from .f5_booking_fixture import five_minute_sandbox
from .f5_extend_day_fixture import grant_extend_day_authority
from .f6_copilot_support import copilot_actor
from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox, auth, client_with_actors, seed_tenant_sandbox

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.adversarial,
    pytest.mark.contract,
]


async def test_f6_ignores_caller_supplied_authority_and_resolves_tenant_truth(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    base = seed_tenant_sandbox(e2e_admin_conn, "f6-copilot-authority")
    sandbox = five_minute_sandbox(e2e_admin_conn, base)
    grant_extend_day_authority(e2e_admin_conn, sandbox)
    actors = {sandbox.token: copilot_actor(sandbox)}
    forged_party = "00000000-0000-4000-8000-000000000009"
    async with client_with_actors(e2e_session_factory, actors) as client:
        response = await client.post(
            "/v1/operational-copilot/interpret",
            json={"text": _extend_text(), "authority_party_id": forged_party},
            headers=auth(sandbox, idempotency_key=f"f6-forged-{uuid4().hex}"),
        )
    assert response.status_code == 200, response.text
    operation = response.json()["operation"]
    assert operation["authority_party_id"] != forged_party
    assert operation["authority_party_id"] is not None


async def test_f6_refuses_extend_day_without_resolved_party_authority(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    base = seed_tenant_sandbox(e2e_admin_conn, "f6-copilot-no-authority")
    sandbox = five_minute_sandbox(e2e_admin_conn, base)
    actors = {sandbox.token: copilot_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        response = await client.post(
            "/v1/operational-copilot/interpret",
            json={"text": _extend_text()},
            headers=auth(sandbox, idempotency_key=f"f6-unauthorized-{uuid4().hex}"),
        )
    assert response.status_code == 403, response.text
    assert "authority" in response.text


def _extend_text(sandbox: TenantSandbox | None = None) -> str:
    return (
        "extend day for incident 00000000-0000-4000-8000-000000000001 "
        "assignment 00000000-0000-4000-8000-000000000002 "
        "from 2026-09-01T17:00:00+00:00 to 2026-09-01T19:00:00+00:00 "
        "source revision 1 location revision 1 availability revision 1 reason probe"
    )
