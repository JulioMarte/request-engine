from __future__ import annotations

import argparse
import json
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

ROLE_PREFIX = "request_engine_%"

# pg_roles deliberately masks rolpassword as ******** for every role. This proof
# runs as the PostgreSQL bootstrap superuser, so use pg_authid for the actual
# nullable credential state as well as the authoritative cluster-global role
# attributes.
ROLE_QUERY = """
    SELECT rolname AS role_name,
           rolsuper AS superuser,
           rolinherit AS inherit,
           rolcreaterole AS create_role,
           rolcreatedb AS create_db,
           rolcanlogin AS can_login,
           rolreplication AS replication,
           rolbypassrls AS bypass_rls,
           rolconnlimit AS connection_limit,
           rolvaliduntil::text AS valid_until,
           rolpassword IS NOT NULL AS has_password
    FROM pg_authid
    WHERE rolname LIKE %s
    ORDER BY rolname
"""

MEMBERSHIP_QUERY = """
    SELECT parent.rolname AS parent_role,
           member.rolname AS member_role,
           membership.inherit_option,
           membership.set_option,
           membership.admin_option
    FROM pg_auth_members membership
    JOIN pg_roles parent ON parent.oid = membership.roleid
    JOIN pg_roles member ON member.oid = membership.member
    WHERE parent.rolname LIKE %s OR member.rolname LIKE %s
    ORDER BY parent.rolname, member.rolname
"""

SETTING_QUERY = """
    SELECT role.rolname AS role_name,
           COALESCE(database.datname, '') AS database_name,
           setting.setconfig AS settings
    FROM pg_db_role_setting setting
    JOIN pg_roles role ON role.oid = setting.setrole
    LEFT JOIN pg_database database ON database.oid = setting.setdatabase
    WHERE role.rolname LIKE %s
    ORDER BY role.rolname, database_name
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export Request Engine cluster-global PostgreSQL role topology"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    with psycopg.connect("", row_factory=dict_row) as conn:
        roles = conn.execute(ROLE_QUERY, (ROLE_PREFIX,)).fetchall()
        memberships = conn.execute(
            MEMBERSHIP_QUERY,
            (ROLE_PREFIX, ROLE_PREFIX),
        ).fetchall()
        settings = conn.execute(SETTING_QUERY, (ROLE_PREFIX,)).fetchall()

    payload = {
        "schema_version": 1,
        "roles": roles,
        "role_memberships": memberships,
        "role_settings": settings,
        "counts": {
            "roles": len(roles),
            "role_memberships": len(memberships),
            "role_settings": len(settings),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
