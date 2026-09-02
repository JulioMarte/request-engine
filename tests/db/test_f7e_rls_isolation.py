from typing import cast
from uuid import UUID

import psycopg
import pytest
from f7e_selection_fixture import (
    F7eSelectionFixture,
    PgConnection,
    create_f7e_selection_fixture,
)

pytestmark = [pytest.mark.postgres, pytest.mark.security]


def _seed_f7e_rows(conn: PgConnection) -> tuple[F7eSelectionFixture, UUID, UUID]:
    world = create_f7e_selection_fixture(conn)
    held, skipped, _other = world.entry_ids
    hold = conn.execute(
        "INSERT INTO request_engine.queue_recall_holds "
        "(organization_id,service_queue_id,queue_entry_id,hold_kind,reason,"
        "created_by_principal_id) "
        "VALUES (%s,%s,%s,'until_customer_initiates','stepped_away',%s) RETURNING id",
        (world.organization_id, world.queue_id, held, world.principal_id),
    ).fetchone()
    assert hold is not None
    fact = conn.execute(
        "INSERT INTO request_engine.queue_selection_facts "
        "(organization_id,service_queue_id,queue_entry_id,selection_kind,reason,"
        "selected_by_principal_id) VALUES (%s,%s,%s,'skip','no_response',%s) RETURNING id",
        (world.organization_id, world.queue_id, skipped, world.principal_id),
    ).fetchone()
    assert fact is not None
    return world, cast(UUID, hold[0]), cast(UUID, fact[0])


def test_f7e_relations_force_rls_and_hide_foreign_tenant_rows(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    first, first_hold, first_fact = _seed_f7e_rows(admin_conn)
    second, _second_hold, _second_fact = _seed_f7e_rows(admin_conn)
    names = ["queue_recall_holds", "queue_selection_facts"]
    rows = admin_conn.execute(
        "SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class c "
        "JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='request_engine' AND relname=ANY(%s::text[])",
        (names,),
    ).fetchall()
    assert len(rows) == 2
    assert all(cast(bool, row[1]) and cast(bool, row[2]) for row in rows)

    app_conn: PgConnection = psycopg.connect(pg_conninfo)
    try:
        app_conn.execute("SET ROLE request_engine_app")
        app_conn.execute(
            "SELECT set_config('request_engine.organization_id',%s,false)",
            (str(first.organization_id),),
        )
        assert app_conn.execute(
            "SELECT id FROM request_engine.queue_recall_holds"
        ).fetchall() == [(first_hold,)]
        assert app_conn.execute(
            "SELECT id FROM request_engine.queue_selection_facts"
        ).fetchall() == [(first_fact,)]

        with pytest.raises(psycopg.Error) as denied:
            app_conn.execute(
                "INSERT INTO request_engine.queue_recall_holds "
                "(organization_id,service_queue_id,queue_entry_id,hold_kind,reason,"
                "created_by_principal_id) "
                "VALUES (%s,%s,%s,'until_customer_initiates','operator_override',%s)",
                (
                    second.organization_id,
                    second.queue_id,
                    second.entry_ids[2],
                    second.principal_id,
                ),
            )
        assert denied.value.sqlstate == "42501"
    finally:
        app_conn.close()
