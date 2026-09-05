from __future__ import annotations

import argparse
import json
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

SCHEMAS = ("request_engine", "request_read", "request_cmd", "request_admin")
_SCHEMALESS_QUERIES = {"roles", "role_memberships", "default_acls"}
QUERIES = {
    "schemas": """
        SELECT n.nspname AS schema_name, pg_get_userbyid(n.nspowner) AS owner
        FROM pg_namespace n WHERE n.nspname = ANY(%s) ORDER BY 1
    """,
    "relations": """
        SELECT n.nspname AS schema_name, c.relname AS relation_name,
               c.relkind::text AS relation_kind, pg_get_userbyid(c.relowner) AS owner,
               c.relrowsecurity AS row_security, c.relforcerowsecurity AS force_row_security,
               c.relispartition AS is_partition,
               CASE WHEN c.relkind IN ('v','m') THEN pg_get_viewdef(c.oid,true) END AS definition
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = ANY(%s) AND c.relkind IN ('r','p','v','m') ORDER BY 1,2
    """,
    "columns": """
        SELECT n.nspname AS schema_name, c.relname AS relation_name, a.attnum AS ordinal,
               a.attname AS column_name,
               pg_catalog.format_type(a.atttypid,a.atttypmod) AS data_type,
               a.attnotnull AS not_null, pg_get_expr(d.adbin,d.adrelid) AS default_expression,
               a.attidentity::text AS identity_kind, a.attgenerated::text AS generated_kind
        FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
        WHERE n.nspname = ANY(%s) AND c.relkind IN ('r','p','v','m')
          AND a.attnum > 0 AND NOT a.attisdropped ORDER BY 1,2,3
    """,
    "constraints": """
        SELECT n.nspname AS schema_name, c.relname AS relation_name, con.conname AS constraint_name,
               con.contype::text AS constraint_type, con.convalidated AS validated,
               pg_get_constraintdef(con.oid,true) AS definition
        FROM pg_constraint con JOIN pg_class c ON c.oid=con.conrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname = ANY(%s) ORDER BY 1,2,3
    """,
    "indexes": """
        SELECT n.nspname AS schema_name, c.relname AS relation_name, i.relname AS index_name,
               x.indisunique AS is_unique, x.indisprimary AS is_primary, x.indisvalid AS is_valid,
               pg_get_indexdef(i.oid) AS definition
        FROM pg_index x JOIN pg_class c ON c.oid=x.indrelid JOIN pg_class i ON i.oid=x.indexrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname = ANY(%s) ORDER BY 1,2,3
    """,
    "view_dependencies": """
        SELECT vn.nspname AS view_schema, view_class.relname AS view_name,
               sn.nspname AS source_schema, source_class.relname AS source_relation
        FROM pg_rewrite rewrite
        JOIN pg_class view_class ON view_class.oid=rewrite.ev_class
        JOIN pg_namespace vn ON vn.oid=view_class.relnamespace
        JOIN pg_depend dependency
          ON dependency.classid='pg_rewrite'::regclass
         AND dependency.objid=rewrite.oid
         AND dependency.refclassid='pg_class'::regclass
        JOIN pg_class source_class ON source_class.oid=dependency.refobjid
        JOIN pg_namespace sn ON sn.oid=source_class.relnamespace
        WHERE vn.nspname = ANY(%s)
          AND view_class.relkind IN ('v','m')
          AND source_class.oid <> view_class.oid
        GROUP BY 1,2,3,4 ORDER BY 1,2,3,4
    """,
    "routines": """
        SELECT n.nspname AS schema_name, p.proname AS routine_name,
               pg_get_function_identity_arguments(p.oid) AS identity_arguments,
               p.prokind::text AS routine_kind, pg_get_userbyid(p.proowner) AS owner,
               p.prosecdef AS security_definer, p.provolatile::text AS volatility,
               p.proconfig AS configuration, pg_get_functiondef(p.oid) AS definition
        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname = ANY(%s) AND p.prokind IN ('f','p') ORDER BY 1,2,3
    """,
    "triggers": """
        SELECT n.nspname AS schema_name, c.relname AS relation_name, t.tgname AS trigger_name,
               t.tgenabled::text AS enabled, pg_get_triggerdef(t.oid,true) AS definition
        FROM pg_trigger t
        JOIN pg_class c ON c.oid=t.tgrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname = ANY(%s) AND NOT t.tgisinternal ORDER BY 1,2,3
    """,
    "policies": """
        SELECT schemaname AS schema_name, tablename AS relation_name, policyname AS policy_name,
               permissive, roles, cmd, qual, with_check
        FROM pg_policies WHERE schemaname = ANY(%s) ORDER BY 1,2,3
    """,
    "table_grants": """
        SELECT CASE WHEN acl.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(acl.grantee) END AS grantee,
               n.nspname AS schema_name, c.relname AS relation_name,
               acl.privilege_type, acl.is_grantable, pg_get_userbyid(acl.grantor) AS grantor
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        CROSS JOIN LATERAL aclexplode(COALESCE(c.relacl, acldefault('r', c.relowner))) AS acl
        WHERE n.nspname = ANY(%s) AND c.relkind IN ('r','p','v','m') ORDER BY 1,2,3,4,5
    """,
    "column_grants": """
        SELECT CASE WHEN acl.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(acl.grantee) END AS grantee,
               n.nspname AS schema_name, c.relname AS relation_name, a.attname AS column_name,
               acl.privilege_type, acl.is_grantable, pg_get_userbyid(acl.grantor) AS grantor
        FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        CROSS JOIN LATERAL aclexplode(a.attacl) AS acl
        WHERE n.nspname = ANY(%s) AND c.relkind IN ('r','p','v','m')
          AND a.attnum > 0 AND NOT a.attisdropped ORDER BY 1,2,3,4,5,6
    """,
    "routine_grants": """
        SELECT CASE WHEN acl.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(acl.grantee) END AS grantee,
               n.nspname AS schema_name, p.proname AS routine_name,
               pg_get_function_identity_arguments(p.oid) AS identity_arguments,
               acl.privilege_type, acl.is_grantable, pg_get_userbyid(acl.grantor) AS grantor
        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        CROSS JOIN LATERAL aclexplode(COALESCE(p.proacl, acldefault('f', p.proowner))) AS acl
        WHERE n.nspname = ANY(%s) AND p.prokind IN ('f','p') ORDER BY 1,2,3,4,5,6
    """,
    "roles": """
        SELECT rolname AS role_name, rolsuper AS superuser, rolinherit AS inherit,
               rolcreaterole AS create_role, rolcreatedb AS create_db, rolcanlogin AS can_login,
               rolbypassrls AS bypass_rls
        FROM pg_roles WHERE rolname LIKE 'request_engine_%' ORDER BY 1
    """,
    "role_memberships": """
        SELECT parent.rolname AS parent_role, member.rolname AS member_role,
               membership.inherit_option, membership.set_option, membership.admin_option
        FROM pg_auth_members membership JOIN pg_roles parent ON parent.oid=membership.roleid
        JOIN pg_roles member ON member.oid=membership.member
        WHERE parent.rolname LIKE 'request_engine_%' OR member.rolname LIKE 'request_engine_%'
        ORDER BY 1,2
    """,
    "default_acls": """
        SELECT pg_get_userbyid(d.defaclrole) AS owner, COALESCE(n.nspname, '') AS schema_name,
               d.defaclobjtype::text AS object_type,
               CASE WHEN acl.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(acl.grantee) END AS grantee,
               acl.privilege_type, acl.is_grantable, pg_get_userbyid(acl.grantor) AS grantor
        FROM pg_default_acl d LEFT JOIN pg_namespace n ON n.oid=d.defaclnamespace
        CROSS JOIN LATERAL aclexplode(d.defaclacl) AS acl
        WHERE pg_get_userbyid(d.defaclrole) LIKE 'request_engine_%' ORDER BY 1,2,3,4,5,6
    """,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Export effective Request Engine PostgreSQL catalog")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload: dict[str, object] = {"schema_version": 2, "schemas": list(SCHEMAS)}
    with psycopg.connect("", row_factory=dict_row) as conn:
        for name, query in QUERIES.items():
            payload[name] = conn.execute(query).fetchall() if name in _SCHEMALESS_QUERIES else conn.execute(query, (list(SCHEMAS),)).fetchall()
    payload["counts"] = {name: len(rows) for name, rows in payload.items() if isinstance(rows, list)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
