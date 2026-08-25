import psycopg
import pytest
from f3_live_ops_fixture import PgConnection, create_live_ops_fixture
from f3_live_ops_race_support import create_principal


@pytest.mark.postgres
@pytest.mark.adversarial
def test_resource_activity_identity_revision_and_terminal_state_are_db_authoritative(
    admin_conn: PgConnection,
) -> None:
    setup = create_live_ops_fixture(admin_conn)
    principal_id = create_principal(admin_conn, setup)
    row = admin_conn.execute(
        "INSERT INTO request_engine.resource_activities "
        "(organization_id,resource_id,activity_kind,started_at,started_by_principal_id) "
        "VALUES (%s,%s,'break','2035-01-01T10:00Z',%s) RETURNING id",
        (setup.organization_id, setup.resource_id, principal_id),
    ).fetchone()
    assert row is not None
    activity_id = row[0]

    with pytest.raises(psycopg.Error) as retarget:
        admin_conn.execute(
            "UPDATE request_engine.resource_activities "
            "SET activity_kind='emergency',revision=revision+1 WHERE id=%s",
            (activity_id,),
        )
    assert retarget.value.sqlstate == "23514"

    with pytest.raises(psycopg.Error) as missing_actor:
        admin_conn.execute(
            "UPDATE request_engine.resource_activities "
            "SET ended_at='2035-01-01T10:05Z',revision=revision+1 WHERE id=%s",
            (activity_id,),
        )
    assert missing_actor.value.sqlstate == "23514"

    admin_conn.execute(
        "UPDATE request_engine.resource_activities "
        "SET ended_at='2035-01-01T10:05Z',ended_by_principal_id=%s,revision=revision+1 "
        "WHERE id=%s",
        (principal_id, activity_id),
    )
    assert admin_conn.execute(
        "SELECT activity_kind,started_at,ended_at,revision "
        "FROM request_engine.resource_activities WHERE id=%s",
        (activity_id,),
    ).fetchone() == (
        "break",
        admin_conn.execute("SELECT '2035-01-01T10:00Z'::timestamptz").fetchone()[0],
        admin_conn.execute("SELECT '2035-01-01T10:05Z'::timestamptz").fetchone()[0],
        2,
    )

    with pytest.raises(psycopg.Error) as terminal:
        admin_conn.execute(
            "UPDATE request_engine.resource_activities "
            "SET ended_at='2035-01-01T10:06Z',revision=revision+1 WHERE id=%s",
            (activity_id,),
        )
    assert terminal.value.sqlstate == "23514"
