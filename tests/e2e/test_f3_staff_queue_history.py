from datetime import UTC, datetime
from uuid import UUID

import pytest

from request_engine.platform.db.session import SessionFactory

from .operational_support import PgConnection
from .tenant_sandbox import actor_for, auth, client_with_actors, seed_tenant_sandbox


def _seed_entry(
    conn: PgConnection,
    *,
    organization_id: UUID,
    queue_id: UUID,
    party_id: UUID,
    status: str,
    admitted_at: datetime,
) -> UUID:
    row = conn.execute(
        "INSERT INTO request_engine.queue_entries "
        "(organization_id,service_queue_id,subject_party_id,status,arrived_at,admitted_at) "
        "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
        (organization_id, queue_id, party_id, status, admitted_at, admitted_at),
    ).fetchone()
    assert row is not None
    return row[0]


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
@pytest.mark.contract
async def test_staff_live_queue_excludes_terminals_and_history_is_paginated(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "f3-staff-history")
    base_actor = actor_for(sandbox)
    actor = type(base_actor)(
        organization_id=base_actor.organization_id,
        principal_id=base_actor.principal_id,
        capabilities=base_actor.capabilities | frozenset({"queue.staff_read"}),
    )
    terminal_ids = [
        _seed_entry(
            e2e_admin_conn,
            organization_id=sandbox.organization_id,
            queue_id=sandbox.queue_id,
            party_id=sandbox.party_id,
            status="cancelled",
            admitted_at=datetime(2035, 1, 1, 10, minute, tzinfo=UTC),
        )
        for minute in range(3)
    ]
    waiting_id = _seed_entry(
        e2e_admin_conn,
        organization_id=sandbox.organization_id,
        queue_id=sandbox.queue_id,
        party_id=sandbox.party_id,
        status="waiting",
        admitted_at=datetime(2035, 1, 1, 11, 0, tzinfo=UTC),
    )
    params = {
        "window_start": "2035-01-01T00:00:00+00:00",
        "window_end": "2035-01-02T00:00:00+00:00",
        "limit": 2,
    }
    async with client_with_actors(e2e_session_factory, {sandbox.token: actor}) as client:
        live = await client.get(
            f"/v1/queues/{sandbox.queue_id}/staff",
            headers=auth(sandbox),
        )
        assert live.status_code == 200, live.text
        assert [UUID(item["queue_entry_id"]) for item in live.json()] == [waiting_id]

        first = await client.get(
            f"/v1/queues/{sandbox.queue_id}/staff/history",
            params=params,
            headers=auth(sandbox),
        )
        assert first.status_code == 200, first.text
        first_body = first.json()
        first_ids = [UUID(item["queue_entry_id"]) for item in first_body["entries"]]
        assert first_ids == terminal_ids[:2]
        assert UUID(first_body["next_cursor"]) == terminal_ids[1]

        second = await client.get(
            f"/v1/queues/{sandbox.queue_id}/staff/history",
            params={**params, "cursor": first_body["next_cursor"]},
            headers=auth(sandbox),
        )
        assert second.status_code == 200, second.text
        second_ids = [UUID(item["queue_entry_id"]) for item in second.json()["entries"]]
        assert second_ids == terminal_ids[2:]
        assert second.json()["next_cursor"] is None

        invalid = await client.get(
            f"/v1/queues/{sandbox.queue_id}/staff/history",
            params={
                "window_start": params["window_end"],
                "window_end": params["window_start"],
            },
            headers=auth(sandbox),
        )
        assert invalid.status_code == 422
