from typing import Any

import pytest
from psycopg import Connection

PgConnection = Connection[Any]


@pytest.mark.postgres
def test_unique_indexes_do_not_have_exact_nonunique_twins(
    admin_conn: PgConnection,
) -> None:
    rows = admin_conn.execute(
        """
        SELECT table_class.relname, unique_index.relname, duplicate_index.relname
        FROM pg_index unique_meta
        JOIN pg_index duplicate_meta
          ON duplicate_meta.indrelid = unique_meta.indrelid
         AND duplicate_meta.indexrelid <> unique_meta.indexrelid
         AND duplicate_meta.indkey = unique_meta.indkey
         AND duplicate_meta.indclass = unique_meta.indclass
         AND duplicate_meta.indcollation = unique_meta.indcollation
         AND duplicate_meta.indoption = unique_meta.indoption
         AND duplicate_meta.indexprs IS NOT DISTINCT FROM unique_meta.indexprs
         AND duplicate_meta.indpred IS NOT DISTINCT FROM unique_meta.indpred
        JOIN pg_class table_class ON table_class.oid = unique_meta.indrelid
        JOIN pg_namespace namespace ON namespace.oid = table_class.relnamespace
        JOIN pg_class unique_index ON unique_index.oid = unique_meta.indexrelid
        JOIN pg_class duplicate_index ON duplicate_index.oid = duplicate_meta.indexrelid
        WHERE namespace.nspname = 'request_engine'
          AND unique_meta.indisunique
          AND NOT duplicate_meta.indisunique
          AND unique_meta.indisvalid
          AND duplicate_meta.indisvalid
        ORDER BY table_class.relname, unique_index.relname, duplicate_index.relname
        """
    ).fetchall()

    assert rows == []


@pytest.mark.postgres
def test_reservations_have_tenant_scoped_temporal_gist_index(
    admin_conn: PgConnection,
) -> None:
    row = admin_conn.execute(
        """
        SELECT indexdef
        FROM pg_indexes
        WHERE schemaname = 'request_engine'
          AND tablename = 'reservations'
          AND indexname = 'reservations_org_during_gist'
        """
    ).fetchone()

    assert row == (
        "CREATE INDEX reservations_org_during_gist ON request_engine.reservations "
        "USING gist (organization_id, during)",
    )


@pytest.mark.postgres
def test_reservation_day_board_predicate_can_use_temporal_gist_access_path(
    admin_conn: PgConnection,
) -> None:
    admin_conn.execute("SET enable_seqscan = off")
    try:
        rows = admin_conn.execute(
            """
            EXPLAIN (COSTS OFF)
            SELECT id
            FROM request_engine.reservations
            WHERE organization_id = '00000000-0000-0000-0000-000000000001'::uuid
              AND during && tstzrange(
                  '2030-01-01T00:00:00Z'::timestamptz,
                  '2030-01-02T00:00:00Z'::timestamptz,
                  '[)'
              )
            ORDER BY lower(during), id
            LIMIT 500
            """
        ).fetchall()
    finally:
        admin_conn.execute("RESET enable_seqscan")

    plan = "\n".join(str(row[0]) for row in rows)
    assert "reservations_org_during_gist" in plan
