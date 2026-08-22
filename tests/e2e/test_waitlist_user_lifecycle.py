from uuid import UUID, uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from .operational_support import PgConnection
from .tenant_sandbox import auth, client_for, seed_tenant_sandbox


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
@pytest.mark.contract
async def test_waitlist_join_read_leave_replay_matches_durable_state(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "waitlist-lifecycle")
    join_key = f"waitlist-join-{uuid4().hex}"
    join_body = {
        "offering_id": str(sandbox.offering_id),
        "subject_party_id": str(sandbox.party_id),
        "location_id": str(sandbox.location_id),
        "preferred_resource_id": str(sandbox.resource_id),
    }

    async with client_for(e2e_session_factory, sandbox) as client:
        created = await client.post(
            "/v1/waitlist",
            headers=auth(sandbox, idempotency_key=join_key),
            json=join_body,
        )
        replay = await client.post(
            "/v1/waitlist",
            headers=auth(sandbox, idempotency_key=join_key),
            json=join_body,
        )
        assert created.status_code == 201, created.text
        assert replay.status_code == 201, replay.text
        assert replay.json() == created.json()
        entry = created.json()
        entry_id = UUID(entry["id"])

        read = await client.get(
            f"/v1/waitlist/{entry_id}",
            headers=auth(sandbox),
        )
        assert read.status_code == 200
        assert read.json() == entry

        leave_key = f"waitlist-leave-{uuid4().hex}"
        leave_body = {"expected_revision": entry["revision"], "reason": "plans changed"}
        left = await client.post(
            f"/v1/waitlist/{entry_id}/leave",
            headers=auth(sandbox, idempotency_key=leave_key),
            json=leave_body,
        )
        left_replay = await client.post(
            f"/v1/waitlist/{entry_id}/leave",
            headers=auth(sandbox, idempotency_key=leave_key),
            json=leave_body,
        )

    assert left.status_code == 200, left.text
    assert left_replay.json() == left.json()
    assert left.json()["status"] == "cancelled"
    row = e2e_admin_conn.execute(
        "SELECT status, revision FROM request_engine.waitlist_entries WHERE id = %s",
        (entry_id,),
    ).fetchone()
    assert row == ("cancelled", entry["revision"] + 1)
    events = e2e_admin_conn.execute(
        "SELECT event_type FROM request_engine.outbox_messages "
        "WHERE aggregate_kind = 'WaitlistEntry' AND aggregate_id = %s ORDER BY event_type",
        (entry_id,),
    ).fetchall()
    assert events == [("waitlist.entry_cancelled.v1",), ("waitlist.entry_joined.v1",)]
