#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

SCHEMA_FILTER = "('request_engine', 'request_read', 'request_cmd', 'request_admin')"
EXPECTED_ROLE_ATTRIBUTES = {
    "request_engine_schema_owner": {
        "can_login": False,
        "superuser": False,
        "bypass_rls": False,
    },
    "request_engine_app": {"can_login": False, "superuser": False, "bypass_rls": False},
    "request_engine_worker": {"can_login": False, "superuser": False, "bypass_rls": False},
    "request_engine_admin": {"can_login": False, "superuser": False, "bypass_rls": True},
}


def fetch_rows(connection: psycopg.Connection[Any], query: str) -> list[dict[str, Any]]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(query)
        return [dict(row) for row in cursor.fetchall()]


def collect_errors(connection: psycopg.Connection[Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []

    unvalidated = fetch_rows(
        connection,
        f"""
        SELECT n.nspname AS schema_name,
               con.conname AS constraint_name
          FROM pg_constraint con
          JOIN pg_namespace n ON n.oid = con.connamespace
         WHERE n.nspname IN {SCHEMA_FILTER}
           AND NOT con.convalidated
         ORDER BY n.nspname, con.conname
        """,
    )
    errors.extend({"kind": "unvalidated_constraint", **row} for row in unvalidated)

    invalid_indexes = fetch_rows(
        connection,
        f"""
        SELECT n.nspname AS schema_name,
               c.relname AS index_name,
               i.indisvalid AS is_valid,
               i.indisready AS is_ready
          FROM pg_index i
          JOIN pg_class c ON c.oid = i.indexrelid
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname IN {SCHEMA_FILTER}
           AND (NOT i.indisvalid OR NOT i.indisready)
         ORDER BY n.nspname, c.relname
        """,
    )
    errors.extend({"kind": "invalid_index", **row} for row in invalid_indexes)

    tenant_without_rls = fetch_rows(
        connection,
        f"""
        SELECT n.nspname AS schema_name,
               c.relname AS relation_name
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname IN {SCHEMA_FILTER}
           AND c.relkind IN ('r', 'p')
           AND EXISTS (
               SELECT 1
                 FROM pg_attribute a
                WHERE a.attrelid = c.oid
                  AND a.attname = 'organization_id'
                  AND a.attnum > 0
                  AND NOT a.attisdropped
           )
           AND NOT c.relrowsecurity
         ORDER BY n.nspname, c.relname
        """,
    )
    errors.extend({"kind": "tenant_relation_without_rls", **row} for row in tenant_without_rls)

    unsafe_definers = fetch_rows(
        connection,
        f"""
        SELECT n.nspname AS schema_name,
               p.proname AS function_name,
               pg_get_function_identity_arguments(p.oid) AS identity_arguments,
               pg_get_userbyid(p.proowner) AS owner,
               p.proconfig AS config
          FROM pg_proc p
          JOIN pg_namespace n ON n.oid = p.pronamespace
         WHERE n.nspname IN {SCHEMA_FILTER}
           AND p.prosecdef
           AND NOT EXISTS (
               SELECT 1
                 FROM unnest(COALESCE(p.proconfig, ARRAY[]::text[])) AS setting
                WHERE setting LIKE 'search_path=%'
           )
         ORDER BY n.nspname, p.proname, pg_get_function_identity_arguments(p.oid)
        """,
    )
    errors.extend(
        {"kind": "security_definer_without_pinned_search_path", **row}
        for row in unsafe_definers
    )

    public_privileges = fetch_rows(
        connection,
        f"""
        WITH public_schema_acl AS (
            SELECT 'schema'::text AS object_kind,
                   n.nspname::text AS object_identity,
                   a.privilege_type
              FROM pg_namespace n
              CROSS JOIN LATERAL aclexplode(
                  COALESCE(n.nspacl, acldefault('n', n.nspowner))
              ) a
             WHERE n.nspname IN {SCHEMA_FILTER}
               AND a.grantee = 0
        ), public_relation_acl AS (
            SELECT 'relation',
                   format('%I.%I', n.nspname, c.relname),
                   a.privilege_type
              FROM pg_class c
              JOIN pg_namespace n ON n.oid = c.relnamespace
              CROSS JOIN LATERAL aclexplode(
                  COALESCE(
                      c.relacl,
                      acldefault(
                          (CASE WHEN c.relkind = 'S' THEN 's' ELSE 'r' END)::"char",
                          c.relowner
                      )
                  )
              ) a
             WHERE n.nspname IN {SCHEMA_FILTER}
               AND c.relkind IN ('r', 'p', 'v', 'm', 'S')
               AND a.grantee = 0
        ), public_function_acl AS (
            SELECT 'function',
                   format(
                       '%I.%I(%s)',
                       n.nspname,
                       p.proname,
                       pg_get_function_identity_arguments(p.oid)
                   ),
                   a.privilege_type
              FROM pg_proc p
              JOIN pg_namespace n ON n.oid = p.pronamespace
              CROSS JOIN LATERAL aclexplode(
                  COALESCE(p.proacl, acldefault('f', p.proowner))
              ) a
             WHERE n.nspname IN {SCHEMA_FILTER}
               AND a.grantee = 0
        )
        SELECT * FROM public_schema_acl
        UNION ALL
        SELECT * FROM public_relation_acl
        UNION ALL
        SELECT * FROM public_function_acl
        ORDER BY object_kind, object_identity, privilege_type
        """,
    )
    errors.extend({"kind": "unexpected_public_privilege", **row} for row in public_privileges)

    role_rows = fetch_rows(
        connection,
        """
        SELECT rolname,
               rolcanlogin AS can_login,
               rolsuper AS superuser,
               rolbypassrls AS bypass_rls
          FROM pg_roles
         WHERE rolname IN (
             'request_engine_schema_owner',
             'request_engine_app',
             'request_engine_worker',
             'request_engine_admin'
         )
         ORDER BY rolname
        """,
    )
    actual_roles = {row["rolname"]: row for row in role_rows}
    for role_name, expected in EXPECTED_ROLE_ATTRIBUTES.items():
        actual = actual_roles.get(role_name)
        if actual is None:
            errors.append({"kind": "missing_runtime_role", "role_name": role_name})
            continue
        mismatch = {
            key: {"expected": expected_value, "actual": actual[key]}
            for key, expected_value in expected.items()
            if actual[key] != expected_value
        }
        if mismatch:
            errors.append(
                {
                    "kind": "unsafe_runtime_role_attributes",
                    "role_name": role_name,
                    "mismatch": mismatch,
                }
            )

    return errors


def collect_warnings(connection: psycopg.Connection[Any]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []

    tenant_without_policy = fetch_rows(
        connection,
        f"""
        SELECT n.nspname AS schema_name,
               c.relname AS relation_name
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname IN {SCHEMA_FILTER}
           AND c.relkind IN ('r', 'p')
           AND c.relrowsecurity
           AND EXISTS (
               SELECT 1
                 FROM pg_attribute a
                WHERE a.attrelid = c.oid
                  AND a.attname = 'organization_id'
                  AND a.attnum > 0
                  AND NOT a.attisdropped
           )
           AND NOT EXISTS (SELECT 1 FROM pg_policy p WHERE p.polrelid = c.oid)
         ORDER BY n.nspname, c.relname
        """,
    )
    warnings.extend(
        {"kind": "tenant_relation_without_policy", **row} for row in tenant_without_policy
    )

    fk_without_prefix_index = fetch_rows(
        connection,
        f"""
        SELECT n.nspname AS schema_name,
               c.relname AS relation_name,
               con.conname AS constraint_name
          FROM pg_constraint con
          JOIN pg_class c ON c.oid = con.conrelid
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname IN {SCHEMA_FILTER}
           AND con.contype = 'f'
           AND NOT EXISTS (
               SELECT 1
                 FROM pg_index i
                WHERE i.indrelid = con.conrelid
                  AND i.indisvalid
                  AND (
                      SELECT array_agg(index_attribute ORDER BY ordinal_position)
                        FROM unnest(i.indkey::smallint[]) WITH ORDINALITY
                             AS indexed(index_attribute, ordinal_position)
                       WHERE ordinal_position <= cardinality(con.conkey)
                  ) = con.conkey
           )
         ORDER BY n.nspname, c.relname, con.conname
        """,
    )
    warnings.extend(
        {"kind": "foreign_key_without_prefix_index", **row}
        for row in fk_without_prefix_index
    )

    duplicate_indexes = fetch_rows(
        connection,
        f"""
        SELECT n.nspname AS schema_name,
               tbl.relname AS relation_name,
               left_idx.relname AS index_a,
               right_idx.relname AS index_b
          FROM pg_index a
          JOIN pg_index b
            ON b.indrelid = a.indrelid
           AND b.indexrelid > a.indexrelid
           AND b.indisunique = a.indisunique
           AND b.indisexclusion = a.indisexclusion
           AND b.indkey = a.indkey
           AND b.indclass = a.indclass
           AND b.indcollation = a.indcollation
           AND b.indoption = a.indoption
           AND COALESCE(b.indexprs::text, '') = COALESCE(a.indexprs::text, '')
           AND COALESCE(b.indpred::text, '') = COALESCE(a.indpred::text, '')
          JOIN pg_class tbl ON tbl.oid = a.indrelid
          JOIN pg_class left_idx ON left_idx.oid = a.indexrelid
          JOIN pg_class right_idx ON right_idx.oid = b.indexrelid
          JOIN pg_namespace n ON n.oid = tbl.relnamespace
         WHERE n.nspname IN {SCHEMA_FILTER}
         ORDER BY n.nspname, tbl.relname, left_idx.relname, right_idx.relname
        """,
    )
    warnings.extend({"kind": "potential_duplicate_index", **row} for row in duplicate_indexes)

    return warnings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit the Request Engine V3 PostgreSQL catalog")
    parser.add_argument(
        "--database",
        help="Database name. Libpq PG* environment variables provide other connection settings.",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        help="Write the audit report to this path.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    connection_kwargs = {"dbname": args.database} if args.database else {}

    with psycopg.connect(**connection_kwargs) as connection:
        errors = collect_errors(connection)
        warnings = collect_warnings(connection)

    report = {"errors": errors, "warnings": warnings}
    rendered = json.dumps(report, indent=2, sort_keys=True)

    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(f"{rendered}\n", encoding="utf-8")

    print(rendered)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
