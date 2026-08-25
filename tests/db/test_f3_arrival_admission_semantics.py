import pytest
from f3_live_ops_fixture import PgConnection, create_live_ops_fixture


@pytest.mark.postgres
@pytest.mark.adversarial
def test_legacy_queue_insert_records_immediate_arrival_and_admission_as_one_fact(
    admin_conn: PgConnection,
) -> None:
    setup = create_live_ops_fixture(admin_conn)
    row = admin_conn.execute(
        "INSERT INTO request_engine.queue_entries "
        "(organization_id,service_queue_id,subject_party_id,offering_id) "
        "VALUES (%s,%s,%s,%s) RETURNING arrived_at,admitted_at",
        (setup.organization_id, setup.queue_id, setup.party_b_id, None),
    ).fetchone()
    assert row is not None
    assert row[0] == row[1]
