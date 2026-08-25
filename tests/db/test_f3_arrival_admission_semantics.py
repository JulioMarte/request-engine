import pytest
from f3_live_ops_fixture import PgConnection, create_live_ops_fixture


@pytest.mark.postgres
@pytest.mark.adversarial
def test_defaulted_queue_timestamps_use_transition_clock_and_preserve_order(
    admin_conn: PgConnection,
) -> None:
    setup = create_live_ops_fixture(admin_conn)
    defaults = dict(
        admin_conn.execute(
            "SELECT a.attname,pg_get_expr(d.adbin,d.adrelid) "
            "FROM pg_attribute a JOIN pg_attrdef d "
            "ON d.adrelid=a.attrelid AND d.adnum=a.attnum "
            "WHERE a.attrelid='request_engine.queue_entries'::regclass "
            "AND a.attname IN ('arrived_at','admitted_at')"
        ).fetchall()
    )
    assert defaults == {
        "arrived_at": "clock_timestamp()",
        "admitted_at": "clock_timestamp()",
    }

    party = admin_conn.execute(
        "INSERT INTO request_engine.parties (organization_id,party_kind,display_name) "
        "VALUES (%s,'person','Arrival Subject') RETURNING id",
        (setup.organization_id,),
    ).fetchone()
    assert party is not None
    row = admin_conn.execute(
        "INSERT INTO request_engine.queue_entries "
        "(organization_id,service_queue_id,subject_party_id) "
        "VALUES (%s,%s,%s) RETURNING arrived_at,admitted_at",
        (setup.organization_id, setup.queue_id, party[0]),
    ).fetchone()
    assert row is not None
    assert row[0] <= row[1]
