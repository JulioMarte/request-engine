from typing import Any

import pytest
from psycopg import Connection

PgConnection = Connection[Any]


@pytest.mark.postgres
def test_i01_every_tenant_owned_foreign_key_is_organization_bound(
    admin_conn: PgConnection,
) -> None:
    """Reject any FK between tenant-owned tables that can omit Organization.

    ADAPT: nullable platform identities retain their existence FK alongside a
    composite tenant FK. A redundant ID-only FK is safe only if every one of
    its column pairs is covered by a validated composite companion. Five
    provenance edges intentionally refer to platform actors; their replacement
    proof is the structural guard plus adversarial writes in the Party suite.
    No entire table or nullable-organization relation is exempted.
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
          AND NOT EXISTS (
              SELECT 1 FROM fk_summary companion
              WHERE companion.source_table = fk_summary.source_table
                AND companion.target_table = fk_summary.target_table
                AND companion.maps_organization
                AND EXISTS (
                    SELECT 1 FROM pg_constraint valid
                    WHERE valid.oid = companion.constraint_oid AND valid.convalidated
                )
                AND NOT EXISTS (
                    SELECT 1 FROM fk_columns original
                    WHERE original.constraint_oid = fk_summary.constraint_oid
                      AND NOT EXISTS (
                          SELECT 1 FROM fk_columns covered
                          WHERE covered.constraint_oid = companion.constraint_oid
                            AND covered.source_column = original.source_column
                            AND covered.target_column = original.target_column
                      )
                )
          )
        ORDER BY source_table, conname
        """
    ).fetchall()

    # Exact semantic exceptions, never a blanket exemption for security tables.
    # Each edge is exercised with foreign-tenant writes in the adjacent suite.
    provenance = {
        (
            "organization_provisioning_facts",
            "organization_provisioning_fact_provisioned_by_principal_id_fkey",
            "principals",
        ),
        (
            "organization_root_provisioning_facts",
            "organization_root_provisioning_provisioned_by_principal_id_fkey",
            "principals",
        ),
        ("staff_memberships", "staff_memberships_established_by_principal_id_fkey", "principals"),
        (
            "principal_authority_grants",
            "principal_authority_grants_granted_by_principal_id_fkey",
            "principals",
        ),
        (
            "principal_authority_grants",
            "principal_authority_grants_revoked_by_principal_id_fkey",
            "principals",
        ),
    }
    guarded = admin_conn.execute(
        """
        SELECT c.relname FROM pg_trigger t
        JOIN pg_class c ON c.oid = t.tgrelid
        WHERE t.tgfoid = 'request_engine.guard_authority_reference_tenant()'::regprocedure
          AND t.tgenabled IN ('O', 'A')
          AND (t.tgtype & 23) = 23
        """
    ).fetchall()
    assert {row[0] for row in guarded} >= {edge[0] for edge in provenance}
    violations = [edge for edge in violations if edge not in provenance]
    assert violations == [], (
        "Tenant-owned FK(s) omit the composite Organization boundary: "
        + ", ".join(f"{source}.{constraint}->{target}" for source, constraint, target in violations)
    )
