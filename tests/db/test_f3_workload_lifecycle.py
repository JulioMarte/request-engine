import psycopg
import pytest
from f3_live_ops_fixture import PgConnection, create_live_ops_fixture


@pytest.mark.postgres
@pytest.mark.adversarial
def test_workload_key_deactivation_and_revision_are_db_authoritative(
    admin_conn: PgConnection,
) -> None:
    setup = create_live_ops_fixture(admin_conn)
    row = admin_conn.execute(
        "INSERT INTO request_engine.operational_workload_classifications "
        "(organization_id,workload_key,display_name) VALUES (%s,'consultation','Consultation') "
        "RETURNING id",
        (setup.organization_id,),
    ).fetchone()
    assert row is not None
    workload_id = row[0]

    with pytest.raises(psycopg.Error) as retarget:
        admin_conn.execute(
            "UPDATE request_engine.operational_workload_classifications "
            "SET workload_key='procedure',revision=revision+1 WHERE id=%s",
            (workload_id,),
        )
    assert retarget.value.sqlstate == "23514"

    with pytest.raises(psycopg.Error) as stale_revision:
        admin_conn.execute(
            "UPDATE request_engine.operational_workload_classifications "
            "SET display_name='Consult',revision=revision+2 WHERE id=%s",
            (workload_id,),
        )
    assert stale_revision.value.sqlstate == "23514"

    admin_conn.execute(
        "UPDATE request_engine.operational_workload_classifications "
        "SET display_name='Consult',revision=revision+1 WHERE id=%s",
        (workload_id,),
    )
    admin_conn.execute(
        "UPDATE request_engine.operational_workload_classifications "
        "SET active=false,revision=revision+1 WHERE id=%s",
        (workload_id,),
    )
    assert admin_conn.execute(
        "SELECT workload_key,display_name,active,revision "
        "FROM request_engine.operational_workload_classifications WHERE id=%s",
        (workload_id,),
    ).fetchone() == ("consultation", "Consult", False, 3)

    with pytest.raises(psycopg.Error) as terminal:
        admin_conn.execute(
            "UPDATE request_engine.operational_workload_classifications "
            "SET display_name='Changed',revision=revision+1 WHERE id=%s",
            (workload_id,),
        )
    assert terminal.value.sqlstate == "23514"

    with pytest.raises(psycopg.Error) as delete:
        admin_conn.execute(
            "DELETE FROM request_engine.operational_workload_classifications WHERE id=%s",
            (workload_id,),
        )
    assert delete.value.sqlstate == "23514"
