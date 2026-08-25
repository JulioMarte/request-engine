from uuid import UUID

from . import operational_support as support


def assert_completed_journey(
    conn: support.PgConnection,
    *,
    entry_id: UUID,
    session_id: UUID,
    expected_workload_id: UUID,
    actual_workload_id: UUID,
) -> None:
    queue_state = conn.execute(
        "SELECT status,expected_workload_classification_id "
        "FROM request_engine.queue_entries WHERE id=%s",
        (entry_id,),
    ).fetchone()
    assert queue_state == ("completed", expected_workload_id)
    session = conn.execute(
        "SELECT status,actual_workload_classification_id "
        "FROM request_engine.service_sessions WHERE id=%s",
        (session_id,),
    ).fetchone()
    assert session == ("completed", actual_workload_id)
    assert actual_workload_id != expected_workload_id
    interruption = conn.execute(
        "SELECT kind,ended_at IS NOT NULL "
        "FROM request_engine.service_session_interruptions WHERE service_session_id=%s",
        (session_id,),
    ).fetchone()
    assert interruption == ("administrative", True)
