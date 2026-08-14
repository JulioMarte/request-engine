#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

APPLICATION_SCHEMAS = ("request_engine", "request_read", "request_cmd", "request_admin")
FINGERPRINT_ROLES = (
    "request_engine_schema_owner",
    "request_engine_app",
    "request_engine_worker",
    "request_engine_admin",
)
FORMAT_VERSION = 1

SCHEMA_FILTER = "('request_engine', 'request_read', 'request_cmd', 'request_admin')"
ROLE_FILTER = (
    "('request_engine_schema_owner', 'request_engine_app', "
    "'request_engine_worker', 'request_engine_admin')"
)

QUERIES = {
    "schemas": f"""
        SELECT n.nspname AS schema_name,
               pg_get_userbyid(n.nspowner) AS owner
          FROM pg_namespace n
         WHERE n.nspname IN {SCHEMA_FILTER}
         ORDER BY n.nspname
    """,
    "roles": f"""
        SELECT rolname,
               rolsuper,
               rolinherit,
               rolcreaterole,
               rolcreatedb,
               rolcanlogin,
               rolreplication,
               rolconnlimit,
               rolbypassrls
          FROM pg_roles
         WHERE rolname IN {ROLE_FILTER}
         ORDER BY rolname
    """,
    "role_memberships": f"""
        SELECT pg_get_userbyid(m.roleid) AS role_name,
               pg_get_userbyid(m.member) AS member_name,
               m.admin_option,
               m.inherit_option,
               m.set_option
          FROM pg_auth_members m
         WHERE pg_get_userbyid(m.roleid) IN {ROLE_FILTER}
            OR pg_get_userbyid(m.member) IN {ROLE_FILTER}
         ORDER BY role_name, member_name
    """,
    "relations": f"""
        SELECT n.nspname AS schema_name,
               c.relname AS relation_name,
               c.relkind,
               pg_get_userbyid(c.relowner) AS owner,
               c.relpersistence,
               c.relrowsecurity,
               c.relforcerowsecurity
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname IN {SCHEMA_FILTER}
           AND c.relkind IN ('r', 'p', 'v', 'm', 'S')
         ORDER BY n.nspname, c.relname
    """,
    "columns": f"""
        SELECT n.nspname AS schema_name,
               c.relname AS relation_name,
               a.attnum AS position,
               a.attname AS column_name,
               pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type,
               a.attnotnull AS not_null,
               a.attidentity AS identity_kind,
               a.attgenerated AS generated_kind,
               CASE
                   WHEN a.attcollation = 0 THEN NULL
                   ELSE coll.collname
               END AS collation,
               pg_get_expr(d.adbin, d.adrelid) AS default_expression
          FROM pg_attribute a
          JOIN pg_class c ON c.oid = a.attrelid
          JOIN pg_namespace n ON n.oid = c.relnamespace
          LEFT JOIN pg_attrdef d
            ON d.adrelid = a.attrelid
           AND d.adnum = a.attnum
          LEFT JOIN pg_collation coll ON coll.oid = a.attcollation
         WHERE n.nspname IN {SCHEMA_FILTER}
           AND c.relkind IN ('r', 'p', 'v', 'm')
           AND a.attnum > 0
           AND NOT a.attisdropped
         ORDER BY n.nspname, c.relname, a.attnum
    """,
    "sequences": f"""
        SELECT n.nspname AS schema_name,
               c.relname AS sequence_name,
               pg_catalog.format_type(s.seqtypid, NULL) AS data_type,
               s.seqstart,
               s.seqincrement,
               s.seqmax,
               s.seqmin,
               s.seqcache,
               s.seqcycle
          FROM pg_sequence s
          JOIN pg_class c ON c.oid = s.seqrelid
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname IN {SCHEMA_FILTER}
         ORDER BY n.nspname, c.relname
    """,
    "types": f"""
        SELECT n.nspname AS schema_name,
               t.typname AS type_name,
               t.typtype AS type_kind,
               pg_get_userbyid(t.typowner) AS owner,
               CASE
                   WHEN t.typtype = 'd' THEN
                       pg_catalog.format_type(t.typbasetype, t.typtypmod)
                   ELSE NULL
               END AS domain_base_type,
               t.typnotnull AS domain_not_null,
               pg_get_expr(t.typdefaultbin, 0) AS domain_default
          FROM pg_type t
          JOIN pg_namespace n ON n.oid = t.typnamespace
         WHERE n.nspname IN {SCHEMA_FILTER}
           AND t.typtype IN ('d', 'e')
         ORDER BY n.nspname, t.typname
    """,
    "enum_labels": f"""
        SELECT n.nspname AS schema_name,
               t.typname AS type_name,
               e.enumsortorder,
               e.enumlabel
          FROM pg_enum e
          JOIN pg_type t ON t.oid = e.enumtypid
          JOIN pg_namespace n ON n.oid = t.typnamespace
         WHERE n.nspname IN {SCHEMA_FILTER}
         ORDER BY n.nspname, t.typname, e.enumsortorder
    """,
    "constraints": f"""
        SELECT n.nspname AS schema_name,
               COALESCE(c.relname, '') AS relation_name,
               con.conname AS constraint_name,
               con.contype AS constraint_type,
               con.condeferrable AS deferrable,
               con.condeferred AS initially_deferred,
               con.convalidated AS validated,
               pg_get_constraintdef(con.oid, true) AS definition
          FROM pg_constraint con
          JOIN pg_namespace n ON n.oid = con.connamespace
          LEFT JOIN pg_class c ON c.oid = con.conrelid
         WHERE n.nspname IN {SCHEMA_FILTER}
         ORDER BY n.nspname, relation_name, con.conname
    """,
    "indexes": f"""
        SELECT n.nspname AS schema_name,
               tbl.relname AS relation_name,
               idx.relname AS index_name,
               i.indisunique AS is_unique,
               i.indisprimary AS is_primary,
               i.indisexclusion AS is_exclusion,
               i.indisvalid AS is_valid,
               i.indisready AS is_ready,
               pg_get_indexdef(i.indexrelid) AS definition
          FROM pg_index i
          JOIN pg_class idx ON idx.oid = i.indexrelid
          JOIN pg_class tbl ON tbl.oid = i.indrelid
          JOIN pg_namespace n ON n.oid = idx.relnamespace
         WHERE n.nspname IN {SCHEMA_FILTER}
         ORDER BY n.nspname, tbl.relname, idx.relname
    """,
    "views": f"""
        SELECT n.nspname AS schema_name,
               c.relname AS view_name,
               c.relkind,
               pg_get_viewdef(c.oid, true) AS definition
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname IN {SCHEMA_FILTER}
           AND c.relkind IN ('v', 'm')
         ORDER BY n.nspname, c.relname
    """,
    "functions": f"""
        SELECT n.nspname AS schema_name,
               p.proname AS function_name,
               pg_get_function_identity_arguments(p.oid) AS identity_arguments,
               pg_get_function_result(p.oid) AS result_type,
               l.lanname AS language,
               pg_get_userbyid(p.proowner) AS owner,
               p.prokind AS routine_kind,
               p.prosecdef AS security_definer,
               p.proleakproof AS leakproof,
               p.proisstrict AS strict,
               p.proretset AS returns_set,
               p.provolatile AS volatility,
               p.proparallel AS parallel_safety,
               ARRAY(
                   SELECT setting
                     FROM unnest(COALESCE(p.proconfig, ARRAY[]::text[])) AS setting
                    ORDER BY setting
               ) AS config,
               pg_get_functiondef(p.oid) AS definition
          FROM pg_proc p
          JOIN pg_namespace n ON n.oid = p.pronamespace
          JOIN pg_language l ON l.oid = p.prolang
         WHERE n.nspname IN {SCHEMA_FILTER}
         ORDER BY n.nspname, p.proname, pg_get_function_identity_arguments(p.oid)
    """,
    "triggers": f"""
        SELECT n.nspname AS schema_name,
               c.relname AS relation_name,
               t.tgname AS trigger_name,
               pg_get_triggerdef(t.oid, true) AS definition
          FROM pg_trigger t
          JOIN pg_class c ON c.oid = t.tgrelid
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname IN {SCHEMA_FILTER}
           AND NOT t.tgisinternal
         ORDER BY n.nspname, c.relname, t.tgname
    """,
    "policies": f"""
        SELECT schemaname AS schema_name,
               tablename AS relation_name,
               policyname AS policy_name,
               permissive,
               ARRAY(
                   SELECT role_name
                     FROM unnest(roles) AS role_name
                    ORDER BY role_name
               ) AS roles,
               cmd,
               qual,
               with_check
          FROM pg_policies
         WHERE schemaname IN {SCHEMA_FILTER}
         ORDER BY schemaname, tablename, policyname
    """,
    "extensions": """
        SELECT e.extname AS extension_name,
               e.extversion AS extension_version,
               n.nspname AS schema_name,
               e.extrelocatable AS relocatable
          FROM pg_extension e
          JOIN pg_namespace n ON n.oid = e.extnamespace
         WHERE e.extname = 'btree_gist'
         ORDER BY e.extname
    """,
    "schema_acl": f"""
        SELECT n.nspname AS object_identity,
               pg_get_userbyid(a.grantor) AS grantor,
               CASE
                   WHEN a.grantee = 0 THEN 'PUBLIC'
                   ELSE pg_get_userbyid(a.grantee)
               END AS grantee,
               a.privilege_type,
               a.is_grantable
          FROM pg_namespace n
          CROSS JOIN LATERAL aclexplode(
              COALESCE(n.nspacl, acldefault('n', n.nspowner))
          ) a
         WHERE n.nspname IN {SCHEMA_FILTER}
         ORDER BY object_identity, grantor, grantee, privilege_type, is_grantable
    """,
    "relation_acl": f"""
        SELECT format('%I.%I', n.nspname, c.relname) AS object_identity,
               pg_get_userbyid(a.grantor) AS grantor,
               CASE
                   WHEN a.grantee = 0 THEN 'PUBLIC'
                   ELSE pg_get_userbyid(a.grantee)
               END AS grantee,
               a.privilege_type,
               a.is_grantable
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
         ORDER BY object_identity, grantor, grantee, privilege_type, is_grantable
    """,
    "function_acl": f"""
        SELECT format(
                   '%I.%I(%s)',
                   n.nspname,
                   p.proname,
                   pg_get_function_identity_arguments(p.oid)
               ) AS object_identity,
               pg_get_userbyid(a.grantor) AS grantor,
               CASE
                   WHEN a.grantee = 0 THEN 'PUBLIC'
                   ELSE pg_get_userbyid(a.grantee)
               END AS grantee,
               a.privilege_type,
               a.is_grantable
          FROM pg_proc p
          JOIN pg_namespace n ON n.oid = p.pronamespace
          CROSS JOIN LATERAL aclexplode(
              COALESCE(p.proacl, acldefault('f', p.proowner))
          ) a
         WHERE n.nspname IN {SCHEMA_FILTER}
         ORDER BY object_identity, grantor, grantee, privilege_type, is_grantable
    """,
    "type_acl": f"""
        SELECT format('%I.%I', n.nspname, t.typname) AS object_identity,
               pg_get_userbyid(a.grantor) AS grantor,
               CASE
                   WHEN a.grantee = 0 THEN 'PUBLIC'
                   ELSE pg_get_userbyid(a.grantee)
               END AS grantee,
               a.privilege_type,
               a.is_grantable
          FROM pg_type t
          JOIN pg_namespace n ON n.oid = t.typnamespace
          CROSS JOIN LATERAL aclexplode(
              COALESCE(t.typacl, acldefault('T', t.typowner))
          ) a
         WHERE n.nspname IN {SCHEMA_FILTER}
           AND t.typtype IN ('d', 'e')
         ORDER BY object_identity, grantor, grantee, privilege_type, is_grantable
    """,
    "default_acl": f"""
        SELECT pg_get_userbyid(d.defaclrole) AS owner,
               CASE
                   WHEN d.defaclnamespace = 0 THEN NULL
                   ELSE n.nspname
               END AS schema_name,
               d.defaclobjtype AS object_type,
               pg_get_userbyid(a.grantor) AS grantor,
               CASE
                   WHEN a.grantee = 0 THEN 'PUBLIC'
                   ELSE pg_get_userbyid(a.grantee)
               END AS grantee,
               a.privilege_type,
               a.is_grantable
          FROM pg_default_acl d
          LEFT JOIN pg_namespace n ON n.oid = d.defaclnamespace
          CROSS JOIN LATERAL aclexplode(d.defaclacl) a
         WHERE pg_get_userbyid(d.defaclrole) IN {ROLE_FILTER}
           AND (d.defaclnamespace = 0 OR n.nspname IN {SCHEMA_FILTER})
         ORDER BY owner, schema_name, object_type, grantor, grantee, privilege_type, is_grantable
    """,
}


def _fetch_rows(connection: psycopg.Connection[Any], query: str) -> list[dict[str, Any]]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(query)
        return [dict(row) for row in cursor.fetchall()]


def build_fingerprint_payload(connection: psycopg.Connection[Any]) -> dict[str, Any]:
    with connection.cursor() as cursor:
        cursor.execute("SHOW server_version_num")
        server_version_num = int(cursor.fetchone()[0])

    return {
        "format_version": FORMAT_VERSION,
        "postgres_major": server_version_num // 10000,
        "application_schemas": list(APPLICATION_SCHEMAS),
        "fingerprint_roles": list(FINGERPRINT_ROLES),
        "catalog": {
            name: _fetch_rows(connection, query) for name, query in QUERIES.items()
        },
    }


def canonical_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate the normalized Request Engine V3 schema fingerprint"
    )
    parser.add_argument(
        "--database",
        help="Database name. Libpq PG* environment variables provide other connection settings.",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        help="Write normalized catalog JSON to this path.",
    )
    parser.add_argument(
        "--sha-output",
        type=Path,
        help="Write the SHA-256 fingerprint to this path.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    connection_kwargs = {"dbname": args.database} if args.database else {}

    with psycopg.connect(**connection_kwargs) as connection:
        payload = build_fingerprint_payload(connection)

    serialized = canonical_bytes(payload)
    digest = hashlib.sha256(serialized).hexdigest()

    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_bytes(serialized + b"\n")
    if args.sha_output:
        args.sha_output.parent.mkdir(parents=True, exist_ok=True)
        args.sha_output.write_text(f"{digest}\n", encoding="utf-8")

    print(digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
