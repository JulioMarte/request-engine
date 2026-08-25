from typing import Any
from uuid import UUID

from . import operational_support as support


def reservation_snapshot(conn: support.PgConnection, reservation_id: UUID) -> Any:
    row = conn.execute(
        "SELECT to_jsonb(r) FROM request_engine.reservations r WHERE id=%s",
        (reservation_id,),
    ).fetchone()
    assert row is not None
    return row[0]


def capacity_claim_snapshot(
    conn: support.PgConnection,
    reservation_id: UUID,
) -> list[Any]:
    return [
        row[0]
        for row in conn.execute(
            "SELECT to_jsonb(c) FROM request_engine.capacity_claims c "
            "WHERE reservation_id=%s ORDER BY id",
            (reservation_id,),
        ).fetchall()
    ]


def assert_completed_journey(
    conn: support.PgConnection,
    *,
    entry_id: UUID,
    session_id: UUID,
    expected_workload_id: UUID,
    actual_workload_id: UUID,
) -> None:
    queue_state = conn.execute(
        "SELECT status,expected_workload_classification_id,service_started_at,completed_at "
        "FROM request_engine.queue_entries WHERE id=%s",
        (entry_id,),
    ).fetchone()
    assert queue_state is not None
    assert queue_state[:2] == ("completed", expected_workload_id)
    session = conn.execute(
        "SELECT status,actual_workload_classification_id,started_at,completed_at "
        "FROM request_engine.service_sessions WHERE id=%s",
        (session_id,),
    ).fetchone()
    assert session is not None
    assert session[:2] == ("completed", actual_workload_id)
    assert queue_state[2:] == session[2:]
    assert actual_workload_id != expected_workload_id
    interruption = conn.execute(
        "SELECT kind,started_at,ended_at "
        "FROM request_engine.service_session_interruptions WHERE service_session_id=%s",
        (session_id,),
    ).fetchone()
    assert interruption is not None
    assert interruption[0] == "administrative"
    assert session[2] <= interruption[1] <= interruption[2] <= session[3]
