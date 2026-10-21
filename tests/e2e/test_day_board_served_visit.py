"""The day board keeps a reservation's served visit after the visit completes.

Protected risk: ``request_read.reservation_day_v1`` used to project only ACTIVE
queue entries, so a booked customer checked in through ``queue.check_in``,
called, served and finished looked untouched on the board afterwards (and the
front desk offered a second check-in). Plausible regressions this must catch:
the served columns missing/NULL after completion, ``served_at`` taken from a
different fact than the ServiceSession completion, ``visit_arrived_at`` lost
once no entry is active, existing active-entry columns changing meaning, the
view losing ``security_invoker`` (and with it invoker RLS), or another
organization seeing the row or its served values.

Execution boundary: owner HTTP operations on the real runtime and the
least-privilege app role on PostgreSQL 18. Oracles: authoritative
``queue_entries``/``service_sessions`` rows read with the admin connection.
"""

from datetime import datetime
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.security.context import ActorContext

from .f3_acceptance_assertions import acceptance_actor
from .front_desk_recall_support import book_and_check_in, day_params
from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox, auth, client_with_actors, seed_tenant_sandbox

pytestmark = [pytest.mark.postgres, pytest.mark.e2e, pytest.mark.contract]


def _front_desk(sandbox: TenantSandbox) -> ActorContext:
    base = acceptance_actor(sandbox)
    return ActorContext(
        base.organization_id,
        base.principal_id,
        base.capabilities | {"appointments.day_board"},
    )


def _board_row(items: list[dict[str, Any]], reservation_id: str) -> dict[str, Any]:
    rows = [item for item in items if item["reservation_id"] == reservation_id]
    assert len(rows) == 1, items
    return rows[0]


def _instant(value: object) -> datetime:
    assert isinstance(value, str), value
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@pytest.mark.asyncio
async def test_day_board_reports_the_served_visit_after_completion(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    clinic = seed_tenant_sandbox(e2e_admin_conn, "served-visit")
    other = seed_tenant_sandbox(e2e_admin_conn, "served-visit-other")
    actors = {clinic.token: _front_desk(clinic), other.token: _front_desk(other)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        reservation, entry = await book_and_check_in(client, clinic)
        reservation_id = reservation["id"]
        entry_id = entry["id"]

        waiting = await client.get(
            "/v1/appointments/day-board", params=day_params(clinic), headers=auth(clinic)
        )
        assert waiting.status_code == 200, waiting.text
        before = _board_row(waiting.json(), reservation_id)
        # Before service: an active visit with an arrival but nothing served yet.
        assert (before["active_queue_entry_count"], before["queue_entry_status"]) == (1, "waiting")
        assert before["served_queue_entry_id"] is None and before["served_at"] is None
        assert before["visit_arrived_at"] is not None

        called = await client.post(
            f"/v1/queues/{clinic.queue_id}/call-next",
            headers=auth(clinic, idempotency_key=f"served-call-{uuid4().hex}"),
        )
        assert called.status_code == 200, called.text
        assert called.json()["id"] == entry_id
        started = await client.post(
            f"/v1/queue-entries/{entry_id}/service/start",
            json={
                "resource_id": str(clinic.resource_id),
                "location_id": str(clinic.location_id),
                "expected_queue_revision": called.json()["revision"],
            },
            headers=auth(clinic, idempotency_key=f"served-start-{uuid4().hex}"),
        )
        assert started.status_code == 201, started.text
        session_id = started.json()["id"]
        serving = await client.get(
            "/v1/appointments/day-board", params=day_params(clinic), headers=auth(clinic)
        )
        in_service = _board_row(serving.json(), reservation_id)
        assert in_service["queue_entry_status"] == "serving"
        assert in_service["served_at"] is None
        completed = await client.post(
            f"/v1/service-sessions/{session_id}/complete",
            json={"expected_revision": started.json()["revision"]},
            headers=auth(clinic, idempotency_key=f"served-complete-{uuid4().hex}"),
        )
        assert completed.status_code == 200, completed.text

        board = await client.get(
            "/v1/appointments/day-board", params=day_params(clinic), headers=auth(clinic)
        )
        assert board.status_code == 200, board.text
        after = _board_row(board.json(), reservation_id)
        foreign = await client.get(
            "/v1/appointments/day-board", params=day_params(other), headers=auth(other)
        )
        assert foreign.status_code == 200, foreign.text
        foreign_items = cast(list[dict[str, Any]], foreign.json())

    # Independent oracle: the authoritative execution and arrival facts.
    fact = e2e_admin_conn.execute(
        "SELECT s.completed_at, q.arrived_at, q.status, s.status "
        "FROM request_engine.service_sessions s "
        "JOIN request_engine.queue_entries q ON q.id = s.queue_entry_id "
        "WHERE s.id = %s",
        (UUID(session_id),),
    ).fetchone()
    assert fact is not None
    completed_at, arrived_at, entry_status, session_status = fact
    assert (entry_status, session_status) == ("completed", "completed")
    assert after["served_queue_entry_id"] == entry_id
    assert _instant(after["served_at"]) == completed_at
    assert _instant(after["visit_arrived_at"]) == arrived_at
    # Existing columns keep their meaning: no active entry remains and the
    # reservation's own attendance check-in was never written by queue.check_in.
    assert after["active_queue_entry_count"] == 0
    assert after["queue_entry_id"] is None and after["queue_entry_status"] is None
    assert after["recall_eligible"] is None
    assert after["checked_in_at"] is None and after["attendance_outcome"] == "pending"
    assert (after["status"], after["revision"]) == (before["status"], before["revision"])
    # The other organization sees neither the row nor any served value of it.
    assert all(item["reservation_id"] != reservation_id for item in foreign_items)
    assert all(item["served_at"] is None for item in foreign_items)

    # Same boundary under the runtime app role directly: invoker RLS on the view.
    statement = text(
        "SELECT reservation_id, served_queue_entry_id, served_at, visit_arrived_at "
        "FROM request_read.reservation_day_v1 WHERE reservation_id = :reservation_id"
    )
    async with tenant_transaction(e2e_session_factory, other.organization_id) as session:
        leaked = (await session.execute(statement, {"reservation_id": reservation_id})).all()
        served_elsewhere = (
            await session.execute(
                text(
                    "SELECT count(*) FROM request_read.reservation_day_v1 "
                    "WHERE served_queue_entry_id = :entry_id OR served_at IS NOT NULL"
                ),
                {"entry_id": entry_id},
            )
        ).scalar_one()
    assert leaked == [] and served_elsewhere == 0
    async with tenant_transaction(e2e_session_factory, clinic.organization_id) as session:
        own = (await session.execute(statement, {"reservation_id": reservation_id})).one()
    assert (str(own.served_queue_entry_id), own.served_at) == (entry_id, completed_at)


def test_served_visit_view_keeps_security_invoker_owner_and_grants(
    e2e_admin_conn: PgConnection,
) -> None:
    row = e2e_admin_conn.execute(
        """
        SELECT c.reloptions, pg_catalog.pg_get_userbyid(c.relowner),
               has_table_privilege('request_engine_app', c.oid, 'SELECT'),
               has_table_privilege('request_engine_app', c.oid, 'INSERT'),
               has_column_privilege('request_engine_app', c.oid, 'served_at', 'SELECT')
          FROM pg_catalog.pg_class c
          JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'request_read' AND c.relname = 'reservation_day_v1'
        """
    ).fetchone()
    assert row is not None
    options, owner, can_select, can_insert, can_read_served = row
    assert "security_invoker=true" in (options or [])
    assert owner == "request_engine_schema_owner"
    assert (can_select, can_insert, can_read_served) == (True, False, True)
