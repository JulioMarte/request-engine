from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection, Error

PgConnection = Connection[Any]


def _uuid_row(conn: PgConnection, sql: str, params: tuple[object, ...]) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


@pytest.mark.postgres
def test_i59_runtime_app_cannot_rewrite_or_delete_material_audit(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    suffix = uuid4().hex
    organization_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"audit-append-{suffix}", f"Audit append {suffix}"),
    )
    principal_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'human', %s)
        RETURNING id
        """,
        (organization_id, f"audit-principal-{suffix}"),
    )
    audit_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.audit_records (
            organization_id,
            actor_principal_id,
            command_name,
            aggregate_kind,
            aggregate_id,
            details
        ) VALUES (%s, %s, 'test.i59', 'TestAggregate', %s, '{"original":true}'::jsonb)
        RETURNING id
        """,
        (organization_id, principal_id, uuid4()),
    )

    app: PgConnection = psycopg.connect(pg_conninfo, autocommit=True)
    try:
        app.execute("SET ROLE request_engine_app")
        app.execute(
            "SELECT set_config('request_engine.organization_id', %s, false)",
            (str(organization_id),),
        )

        # request_engine_app intentionally has UPDATE on ordinary tenant tables.
        # The audit-specific append-only trigger is therefore the decisive backstop.
        with pytest.raises(Error) as update_error:
            app.execute(
                "UPDATE request_engine.audit_records SET details = '{\"rewritten\":true}'::jsonb WHERE id = %s",
                (audit_id,),
            )
        assert update_error.value.sqlstate == "55000"

        # Runtime app has no DELETE privilege at all; normal operation cannot erase history.
        with pytest.raises(Error) as delete_error:
            app.execute("DELETE FROM request_engine.audit_records WHERE id = %s", (audit_id,))
        assert delete_error.value.sqlstate == "42501"
    finally:
        app.close()

    original = admin_conn.execute(
        "SELECT command_name, details FROM request_engine.audit_records WHERE id = %s",
        (audit_id,),
    ).fetchone()
    assert original == ("test.i59", {"original": True})
