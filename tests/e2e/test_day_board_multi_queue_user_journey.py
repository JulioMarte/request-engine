from typing import cast
from uuid import UUID, uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from .front_desk_recall_support import book_and_check_in, day_params, front_desk_actor
from .operational_support import PgConnection
from .tenant_sandbox import auth, client_with_actors, seed_tenant_sandbox


def _second_queue(conn: PgConnection, *, organization_id: UUID, location_id: UUID, offering_id: UUID) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.service_queues (
            organization_id, location_id, offering_id, queue_key, display_name
        ) VALUES (%s, %s, %s, %s, 'Second operational stage')
        RETURNING id
        """,
        (organization_id, location_id, offering_id, f"stage-two-{uuid4().hex}"),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
async def test_day_board_exposes_multi_queue_ambiguity_created_through_api(
    e2e_admin_conn: PgConnection, e2e_session_factory: SessionFactory
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "multi-queue-journey")
    second_queue = _second_queue(
        e2e_admin_conn,
        organization_id=sandbox.organization_id,
        location_id=sandbox.location_id,
        offering_id=sandbox.offering_id,
    )
    async with client_with_actors(
        e2e_session_factory, {sandbox.token: front_desk_actor(sandbox)}
    ) as client:
        reservation, first_entry = await book_and_check_in(client, sandbox)
        second = await client.post(
            f"/v1/queues/{second_queue}/check-in",
            json={
                "subject_party_id": str(sandbox.party_id),
                "reservation_id": reservation["id"],
            },
            headers=auth(sandbox, idempotency_key=f"stage-two-{uuid4().hex}"),
        )
        assert second.status_code == 201, second.text
        assert second.json()["id"] != first_entry["id"]

        board = await client.get(
            "/v1/appointments/day-board",
            params=day_params(sandbox),
            headers=auth(sandbox),
        )
        assert board.status_code == 200
        item = board.json()[0]
        assert item["reservation_id"] == reservation["id"]
        assert item["active_queue_entry_count"] == 2
        assert item["queue_entry_id"] is None
        assert item["queue_entry_status"] is None
        assert item["recall_eligible"] is None
        assert item["recall_hold_id"] is None
