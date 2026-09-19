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
def test_temporal_gist_supports_tenant_equality_and_range_overlap(
    admin_conn: PgConnection,
) -> None:
    # ADAPT: an empty-table cost estimate may legitimately prefer the tenant
    # B-tree. Prove supported access operators instead of freezing a planner
    # choice. Real day-board behavior is covered by its PostgreSQL reader tests.
    rows = admin_conn.execute(
        """
        SELECT DISTINCT a.attname, o.oprname
          FROM pg_index i
          JOIN pg_class idx ON idx.oid = i.indexrelid
          JOIN pg_am am ON am.oid = idx.relam AND am.amname = 'gist'
          JOIN LATERAL unnest(i.indkey, i.indclass) AS keys(attnum, opclass) ON true
          JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = keys.attnum
          JOIN pg_opclass opc ON opc.oid = keys.opclass
          JOIN pg_amop operation ON operation.amopfamily = opc.opcfamily
          JOIN pg_operator o ON o.oid = operation.amopopr
         WHERE i.indexrelid = 'request_engine.reservations_org_during_gist'::regclass
           AND i.indisvalid AND i.indisready AND operation.amoppurpose = 's'
        """
    ).fetchall()
    assert {("organization_id", "="), ("during", "&&")} <= set(rows)


@pytest.mark.postgres
def test_unsupported_admin_health_views_are_absent(
    admin_conn: PgConnection,
) -> None:
    rows = admin_conn.execute(
        """
        SELECT c.relname
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'request_admin'
          AND c.relkind = 'v'
          AND c.relname IN ('outbox_health_v1', 'scheduled_action_health_v1')
        ORDER BY c.relname
        """
    ).fetchall()

    assert rows == []


@pytest.mark.postgres
def test_worker_dead_letters_operator_projection_remains_supported(
    admin_conn: PgConnection,
) -> None:
    row = admin_conn.execute(
        "SELECT pg_get_viewdef('request_admin.worker_dead_letters_v1'::regclass, true)"
    ).fetchone()

    assert row is not None
    definition = str(row[0])
    assert "scheduled_actions" in definition
    assert "outbox_messages" in definition
    assert "provider_events" in definition
    assert "'scheduled_action'::text" in definition
    assert "'outbox_message'::text" in definition
    assert "'provider_event'::text" in definition
