from typing import Any

import pytest
from psycopg import Connection

PgConnection = Connection[Any]


@pytest.mark.postgres
def test_i01_every_tenant_owned_foreign_key_is_organization_bound(
    admin_conn: PgConnection,
) -> None:
    """Reject any FK between tenant-owned tables that can omit Organization.

    A relation is tenant-owned for this catalog proof when it carries an
    `organization_id` column.  For every FK whose source and target are both
    tenant-owned, the FK must include source.organization_id mapped to
    target.organization_id in the same composite key.  This is the database
    backstop that prevents a globally unique UUID from becoming a cross-tenant
    reference capability.
    """

    violations = admin_conn.execute(
        """
        WITH tenant_tables AS (
            SELECT c.oid AS relid
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'request_engine'
              AND c.relkind IN ('r', 'p')
              AND EXISTS (
                  SELECT 1
                  FROM pg_attribute a
                  WHERE a.attrelid = c.oid
                    AND a.attname = 'organization_id'
                    AND NOT a.attisdropped
              )
        ),
        fk_columns AS (
            SELECT
                con.oid AS constraint_oid,
                con.conname,
                src.relname AS source_table,
                dst.relname AS target_table,
                ord.ordinality,
                src_att.attname AS source_column,
                dst_att.attname AS target_column
            FROM pg_constraint con
            JOIN tenant_tables src_t ON src_t.relid = con.conrelid
            JOIN tenant_tables dst_t ON dst_t.relid = con.confrelid
            JOIN pg_class src ON src.oid = con.conrelid
            JOIN pg_class dst ON dst.oid = con.confrelid
            JOIN LATERAL unnest(con.conkey, con.confkey)
                WITH ORDINALITY AS ord(src_attnum, dst_attnum, ordinality) ON true
            JOIN pg_attribute src_att
              ON src_att.attrelid = con.conrelid
             AND src_att.attnum = ord.src_attnum
            JOIN pg_attribute dst_att
              ON dst_att.attrelid = con.confrelid
             AND dst_att.attnum = ord.dst_attnum
            WHERE con.contype = 'f'
        ),
        fk_summary AS (
            SELECT
                constraint_oid,
                conname,
                source_table,
                target_table,
                bool_or(
                    source_column = 'organization_id'
                    AND target_column = 'organization_id'
                ) AS maps_organization
            FROM fk_columns
            GROUP BY constraint_oid, conname, source_table, target_table
        )
        SELECT source_table, conname, target_table
        FROM fk_summary
        WHERE NOT maps_organization
        ORDER BY source_table, conname
        """
    ).fetchall()

    assert violations == [], (
        "Tenant-owned FK(s) omit the composite Organization boundary: "
        + ", ".join(f"{source}.{constraint}->{target}" for source, constraint, target in violations)
    )
