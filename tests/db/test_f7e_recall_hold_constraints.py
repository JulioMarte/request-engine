import pytest
from psycopg.errors import CheckViolation

from f7e_selection_fixture import PgConnection, create_f7e_selection_fixture

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_postgres_rejects_free_text_recall_hold_reason(admin_conn: PgConnection) -> None:
    world = create_f7e_selection_fixture(admin_conn)
    first = world.entry_ids[0]

    with pytest.raises(CheckViolation):
        admin_conn.execute(
            "INSERT INTO request_engine.queue_recall_holds "
            "(organization_id,service_queue_id,queue_entry_id,hold_kind,reason,"
            "created_by_principal_id) "
            "VALUES (%s,%s,%s,'until_customer_initiates',%s,%s)",
            (
                world.organization_id,
                world.queue_id,
                first,
                "patient has chest pain",
                world.principal_id,
            ),
        )


def test_postgres_accepts_closed_recall_hold_reason(admin_conn: PgConnection) -> None:
    world = create_f7e_selection_fixture(admin_conn)
    first = world.entry_ids[0]
    row = admin_conn.execute(
        "INSERT INTO request_engine.queue_recall_holds "
        "(organization_id,service_queue_id,queue_entry_id,hold_kind,reason,"
        "created_by_principal_id) "
        "VALUES (%s,%s,%s,'until_customer_initiates','stepped_away',%s) "
        "RETURNING reason",
        (world.organization_id, world.queue_id, first, world.principal_id),
    ).fetchone()
    assert row == ("stepped_away",)


def test_postgres_rejects_unregistered_release_reason(admin_conn: PgConnection) -> None:
    world = create_f7e_selection_fixture(admin_conn)
    first = world.entry_ids[0]
    hold = admin_conn.execute(
        "INSERT INTO request_engine.queue_recall_holds "
        "(organization_id,service_queue_id,queue_entry_id,hold_kind,reason,"
        "created_by_principal_id) "
        "VALUES (%s,%s,%s,'until_customer_initiates','operator_override',%s) RETURNING id",
        (world.organization_id, world.queue_id, first, world.principal_id),
    ).fetchone()
    assert hold is not None

    with pytest.raises(CheckViolation):
        admin_conn.execute(
            "UPDATE request_engine.queue_recall_holds SET released_at=clock_timestamp(),"
            "released_by_principal_id=%s,release_reason='patient_requested' WHERE id=%s",
            (world.principal_id, hold[0]),
        )
