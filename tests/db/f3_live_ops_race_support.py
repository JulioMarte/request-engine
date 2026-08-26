from typing import cast
from uuid import UUID, uuid4

from f3_live_ops_fixture import LiveOpsFixture, PgConnection


def create_principal(conn: PgConnection, setup: LiveOpsFixture) -> UUID:
    row = conn.execute(
        "INSERT INTO request_engine.principals "
        "(organization_id,principal_kind,external_subject) "
        "VALUES (%s,'agent',%s) RETURNING id",
        (setup.organization_id, f"f3-race-{uuid4().hex}"),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def create_active_session(conn: PgConnection, setup: LiveOpsFixture, entry_id: UUID) -> UUID:
    started_at = conn.execute(
        "SELECT called_at + interval '1 minute' FROM request_engine.queue_entries WHERE id=%s",
        (entry_id,),
    ).fetchone()
    assert started_at is not None
    with conn.transaction():
        conn.execute(
            "UPDATE request_engine.queue_entries SET status='serving',service_started_at=%s,"
            "revision=revision+1 WHERE id=%s",
            (started_at[0], entry_id),
        )
        row = conn.execute(
            "INSERT INTO request_engine.service_sessions "
            "(organization_id,queue_entry_id,resource_id,location_id,"
            "actual_workload_classification_id,started_at) VALUES (%s,%s,%s,%s,%s,%s) "
            "RETURNING id",
            (
                setup.organization_id,
                entry_id,
                setup.resource_id,
                setup.location_id,
                setup.actual_workload_id,
                started_at[0],
            ),
        ).fetchone()
        assert row is not None
    return cast(UUID, row[0])


def create_paused_session(conn: PgConnection, setup: LiveOpsFixture) -> tuple[UUID, UUID]:
    principal_id = create_principal(conn, setup)
    session_id = create_active_session(conn, setup, setup.entry_a_id)
    started = conn.execute(
        "SELECT started_at + interval '1 minute' FROM request_engine.service_sessions WHERE id=%s",
        (session_id,),
    ).fetchone()
    assert started is not None
    with conn.transaction():
        conn.execute(
            "UPDATE request_engine.service_sessions SET status='paused',revision=revision+1 "
            "WHERE id=%s",
            (session_id,),
        )
        conn.execute(
            "INSERT INTO request_engine.service_session_interruptions "
            "(organization_id,service_session_id,kind,started_at,started_by_principal_id) "
            "VALUES (%s,%s,'break',%s,%s)",
            (setup.organization_id, session_id, started[0], principal_id),
        )
    return session_id, principal_id
