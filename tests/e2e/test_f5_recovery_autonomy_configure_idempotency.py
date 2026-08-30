from __future__ import annotations

from typing import Any, cast
from uuid import uuid4

import pytest
from httpx import Response

from request_engine.platform.db.session import SessionFactory

from .f5_recovery_support import f5_actor
from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox, auth, client_with_actors, seed_tenant_sandbox

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e, pytest.mark.postgres]
pytestmark += [pytest.mark.contract, pytest.mark.invariant, pytest.mark.adversarial]

_GRANT = {"enabled": True, "max_delay_minutes": 30, "max_auto_actions_per_incident": 2}
_HIGHER = {"enabled": True, "max_delay_minutes": 60, "max_auto_actions_per_incident": 2}
_OTHER = {"enabled": True, "max_delay_minutes": 45, "max_auto_actions_per_incident": 3}


async def _configure(
    session_factory: SessionFactory,
    sandbox: TenantSandbox,
    *,
    key: str,
    body: dict[str, Any],
) -> Response:
    async with client_with_actors(session_factory, {sandbox.token: f5_actor(sandbox)}) as client:
        return await client.post(
            f"/v1/operational-recovery/queues/{sandbox.queue_id}/autonomy-policy",
            json=body,
            headers=auth(sandbox, idempotency_key=key),
        )


def _stored_delay(conn: PgConnection, sandbox: TenantSandbox) -> int:
    row = conn.execute(
        "SELECT max_delay_minutes FROM request_engine.operational_recovery_autonomy_policies "
        "WHERE organization_id=%s AND service_queue_id=%s",
        (sandbox.organization_id, sandbox.queue_id),
    ).fetchone()
    assert row is not None
    return int(row[0])


async def test_configure_replays_same_key_and_conflicts_on_different_payload(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "f5-autonomy-configure-idempotency")
    key = f"f5-autonomy-configure-{uuid4().hex}"

    first = await _configure(e2e_session_factory, sandbox, key=key, body=_GRANT)
    assert first.status_code == 200, first.text
    assert first.json()["max_delay_minutes"] == 30

    replay = await _configure(e2e_session_factory, sandbox, key=key, body=_GRANT)
    assert replay.status_code == 200, replay.text
    assert replay.json() == first.json()

    conflicting = await _configure(e2e_session_factory, sandbox, key=key, body=_HIGHER)
    assert conflicting.status_code == 409, conflicting.text
    error = cast(dict[str, Any], conflicting.json())["error"]
    assert error["code"] == "idempotency_conflict"
    assert error["details"]["idempotency_key"] == key
    assert error["message"] == "the idempotency key was already used for a different command"
    assert _stored_delay(e2e_admin_conn, sandbox) == 30

    other_key = f"f5-autonomy-configure-{uuid4().hex}"
    changed = await _configure(e2e_session_factory, sandbox, key=other_key, body=_OTHER)
    assert changed.status_code == 200, changed.text
    assert changed.json()["max_delay_minutes"] == 45
    assert _stored_delay(e2e_admin_conn, sandbox) == 45

    replay_after_change = await _configure(e2e_session_factory, sandbox, key=key, body=_GRANT)
    assert replay_after_change.status_code == 200, replay_after_change.text
    assert replay_after_change.json() == first.json()
    assert _stored_delay(e2e_admin_conn, sandbox) == 45
