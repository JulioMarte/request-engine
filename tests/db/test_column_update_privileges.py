from typing import Any

from psycopg import Connection

PgConnection = Connection[Any]

_COLUMN_UPDATE_AUTHORITY = {
    "operational_recovery_executions": {
        "communication_task_id",
        "completed_at",
        "failure_code",
        "resulting_reservation_revision",
        "status",
    },
    "queue_entry_recall_holds": {"release_kind", "released_at"},
    "queue_entry_skips": {"consumed_at", "consumed_by_entry_id"},
}


def test_app_update_authority_is_column_scoped(admin_conn: PgConnection) -> None:
    for table, expected_columns in _COLUMN_UPDATE_AUTHORITY.items():
        table_ref = f"request_engine.{table}"
        has_table_update = admin_conn.execute(
            "SELECT has_table_privilege('request_engine_app', %s, 'UPDATE')",
            (table_ref,),
        ).fetchone()
        assert has_table_update == (False,)

        actual_columns = {
            row[0]
            for row in admin_conn.execute(
                """
                SELECT a.attname
                FROM pg_attribute a
                WHERE a.attrelid = %s::regclass
                  AND a.attnum > 0
                  AND NOT a.attisdropped
                  AND has_column_privilege(
                      'request_engine_app', a.attrelid, a.attnum, 'UPDATE'
                  )
                ORDER BY a.attname
                """,
                (table_ref,),
            ).fetchall()
        }
        assert actual_columns == expected_columns
