from __future__ import annotations

from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from .f3_acceptance_assertions import seed_walk_in_subject
from .f4_capacity_support import seed_today_schedule
from .f4_operational_day_support import configure_projection
from .f5_booking_fixture import five_minute_sandbox
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
    pytest.mark.concurrency,
]


async def test_f5_stop_and_reopen_intake_is_transactional_and_idempotent(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    base = seed_tenant_sandbox(e2e_admin_conn, "f5-intake-control")
    sandbox = five_minute_sandbox(e2e_admin_conn, base)
    seed_today_schedule(e2e_admin_conn, sandbox)
    actors = {sandbox.token: f5_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        await configure_projection(client, sandbox)
        _, slots = await book_commitments(client, e2e_admin_conn, sandbox)
        restrict_source_to_first_six(e2e_admin_conn, sandbox, slots)
        proposal = await create_proposal(client, sandbox)
        incident_id = seed_incident_for_proposal(e2e_admin_conn, sandbox, proposal)
        source_revision = _source_revision(proposal)

        stopped_subject = seed_walk_in_subject(e2e_admin_conn, sandbox)
        before_count = _queue_entry_count(e2e_admin_conn, sandbox)
        key = f"f5-stop-intake-{uuid4().hex}"
        stop_body: dict[str, object] = {
            "expected_source_revision": source_revision,
            "expected_intake_revision": 1,
            "accepting": False,
            "reason": "recovery shortfall",
        }
        stopped = await client.post(
            f"/v1/operational-recovery/incidents/{incident_id}/intake-control",
            json=stop_body,
            headers=auth(sandbox, idempotency_key=key),
        )
        replay = await client.post(
            f"/v1/operational-recovery/incidents/{incident_id}/intake-control",
            json=stop_body,
            headers=auth(sandbox, idempotency_key=key),
        )
        assert stopped.status_code == replay.status_code == 200
        assert stopped.json()["action_kind"] == "stop_intake"
        assert stopped.json()["status"] == "succeeded"
        assert replay.json()["id"] == stopped.json()["id"]
        assert _intake_state(e2e_admin_conn, sandbox)[:2] == (False, 2)

        conflicting = await client.post(
            f"/v1/operational-recovery/incidents/{incident_id}/intake-control",
            json={**stop_body, "reason": "different intent"},
            headers=auth(sandbox, idempotency_key=key),
        )
        assert conflicting.status_code == 409, conflicting.text

        blocked = await _walk_in(client, sandbox, stopped_subject)
        assert blocked.status_code == 409, blocked.text
        assert blocked.json()["error"]["code"] == "queue_intake_stopped"
        assert _queue_entry_count(e2e_admin_conn, sandbox) == before_count

        reopened = await client.post(
            f"/v1/operational-recovery/incidents/{incident_id}/intake-control",
            json={
                "expected_source_revision": source_revision,
                "expected_intake_revision": 2,
                "accepting": True,
                "reason": "operator reopened intake",
            },
            headers=auth(sandbox, idempotency_key=f"f5-reopen-intake-{uuid4().hex}"),
        )
        assert reopened.status_code == 200, reopened.text
        assert reopened.json()["action_kind"] == "reopen_intake"
        assert reopened.json()["status"] == "succeeded"
        assert _intake_state(e2e_admin_conn, sandbox)[:2] == (True, 3)

        admitted = await _walk_in(client, sandbox, stopped_subject)
        assert admitted.status_code == 201, admitted.text
        assert _queue_entry_count(e2e_admin_conn, sandbox) == before_count + 1


def _source_revision(proposal: dict[str, Any]) -> int:
    checkpoint = cast(dict[str, Any], proposal["source_checkpoint"])
    return cast(int, checkpoint["recovery_source_revision"])


async def _walk_in(client: Any, sandbox: TenantSandbox, subject_id: UUID) -> Any:
    return await client.post(
        f"/v1/queues/{sandbox.queue_id}/check-in",
        json={"subject_party_id": str(subject_id)},
        headers=auth(sandbox, idempotency_key=f"walk-in-{uuid4().hex}"),
    )


def _intake_state(conn: PgConnection, sandbox: TenantSandbox) -> tuple[object, ...]:
    row = conn.execute(
        "SELECT accepting,revision,reason FROM request_engine.service_queue_intake_controls "
        "WHERE organization_id=%s AND service_queue_id=%s",
        (sandbox.organization_id, sandbox.queue_id),
    ).fetchone()
    assert row is not None
    return tuple(row)


def _queue_entry_count(conn: PgConnection, sandbox: TenantSandbox) -> int:
    row = conn.execute(
        "SELECT count(*) FROM request_engine.queue_entries "
        "WHERE organization_id=%s AND service_queue_id=%s",
        (sandbox.organization_id, sandbox.queue_id),
    ).fetchone()
    assert row is not None
    return cast(int, row[0])
