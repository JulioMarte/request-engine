import psycopg
import pytest
from f3_live_ops_fixture import PgConnection, create_live_ops_fixture
from f3_live_ops_race_support import create_active_session, create_principal


@pytest.mark.postgres
@pytest.mark.adversarial
def test_interruption_cannot_predate_service_execution_and_rolls_back(
    admin_conn: PgConnection,
) -> None:
    setup = create_live_ops_fixture(admin_conn)
    principal_id = create_principal(admin_conn, setup)
    session_id = create_active_session(admin_conn, setup, setup.entry_a_id)
    started = admin_conn.execute(
        "SELECT started_at - interval '1 second' FROM request_engine.service_sessions WHERE id=%s",
        (session_id,),
    ).fetchone()
    assert started is not None

    with pytest.raises(psycopg.Error) as error, admin_conn.transaction():
        admin_conn.execute(
            "UPDATE request_engine.service_sessions SET status='paused',revision=revision+1 "
            "WHERE id=%s",
            (session_id,),
        )
        admin_conn.execute(
            "INSERT INTO request_engine.service_session_interruptions "
            "(organization_id,service_session_id,kind,started_at,started_by_principal_id) "
            "VALUES (%s,%s,'break',%s,%s)",
            (setup.organization_id, session_id, started[0], principal_id),
        )

    assert error.value.sqlstate == "23514"
    assert "cannot predate execution" in str(error.value)
    assert admin_conn.execute(
        "SELECT status,revision FROM request_engine.service_sessions WHERE id=%s",
        (session_id,),
    ).fetchone() == ("active", 1)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.service_session_interruptions "
        "WHERE service_session_id=%s",
        (session_id,),
    ).fetchone() == (0,)
