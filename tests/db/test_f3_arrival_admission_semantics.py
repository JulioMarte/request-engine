import pytest
from f3_live_ops_fixture import PgConnection, create_live_ops_fixture


@pytest.mark.postgres
@pytest.mark.adversarial
def test_legacy_queue_insert_records_immediate_arrival_and_admission_as_one_fact(
    admin_conn: PgConnection,
) -> None:
    setup = create_live_ops_fixture(admin_conn)
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
    assert row[0] == row[1]
