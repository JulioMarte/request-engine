from uuid import uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from . import operational_support as support
from .http_isolation_probes import isolation_actor
from .tenant_sandbox import auth, client_with_actors, first_slot, seed_tenant_sandbox

pytestmark = [pytest.mark.postgres, pytest.mark.e2e]
_WINDOW = {
    "window_start": "2030-01-07T13:00:00+00:00",
    "window_end": "2030-01-07T16:00:00+00:00",
}


@pytest.mark.asyncio
async def test_day_board_projects_live_operator_truth_and_keeps_cancelled_reservation(
    e2e_admin_conn: support.PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    tenant = seed_tenant_sandbox(e2e_admin_conn, "day-board")
    actor = isolation_actor(tenant)
    async with client_with_actors(e2e_session_factory, {tenant.token: actor}) as client:
        slot = await first_slot(client, tenant)
        booked = await client.post(
            "/v1/appointments",
            json={"option_id": slot["option_id"], "subject_party_id": str(tenant.party_id)},
            headers=auth(tenant, idempotency_key=f"day-board-book-{uuid4().hex}"),
        )
        assert booked.status_code == 201, booked.text
        reservation = booked.json()
        reservation_id = reservation["id"]

        attendance = await client.post(
            f"/v1/appointments/{reservation_id}/attendance",
            json={"response": "accepted", "expected_revision": reservation["revision"]},
            headers=auth(tenant, idempotency_key=f"day-board-attendance-{uuid4().hex}"),
        )
        assert attendance.status_code == 200, attendance.text
        arrival = await client.post(
            f"/v1/appointments/{reservation_id}/arrival-estimate",
            json={
                "estimated_arrival_at": "2030-01-07T13:20:00+00:00",
                "expected_revision": attendance.json()["reservation_revision"],
            },
            headers=auth(tenant, idempotency_key=f"day-board-arrival-{uuid4().hex}"),
        )
        assert arrival.status_code == 200, arrival.text

        board = await client.get("/v1/appointments/day-board", params=_WINDOW, headers=auth(tenant))
        assert board.status_code == 200, board.text
        rows = [row for row in board.json() if row["reservation_id"] == reservation_id]
        assert len(rows) == 1
        row = rows[0]
        expected_name = e2e_admin_conn.execute(
            "SELECT display_name FROM request_engine.parties WHERE id = %s", (tenant.party_id,)
        ).fetchone()
        assert expected_name is not None
        assert row["subject_display_name"] == expected_name[0]
        assert row["status"] == "confirmed"
        assert row["attendance_status"] == "accepted"
        assert row["attendance_outcome"] == "pending"
        assert row["estimated_arrival_at"] == arrival.json()["estimated_arrival_at"]
        assert row["arrival_estimate_source_kind"] == arrival.json()["source_kind"]

        cancelled = await client.post(
            f"/v1/appointments/{reservation_id}/cancel",
            json={"expected_revision": arrival.json()["reservation_revision"], "reason": "e2e"},
            headers=auth(tenant, idempotency_key=f"day-board-cancel-{uuid4().hex}"),
        )
        assert cancelled.status_code == 200, cancelled.text
        board = await client.get("/v1/appointments/day-board", params=_WINDOW, headers=auth(tenant))
        rows = [row for row in board.json() if row["reservation_id"] == reservation_id]
        assert len(rows) == 1 and rows[0]["status"] == "cancelled"


def test_day_board_view_is_security_invoker(e2e_admin_conn: support.PgConnection) -> None:
    row = e2e_admin_conn.execute(
        """
        SELECT c.reloptions
          FROM pg_catalog.pg_class c
          JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'request_read' AND c.relname = 'reservation_day_v1'
        """
    ).fetchone()
    assert row is not None
    assert "security_invoker=true" in (row[0] or [])
