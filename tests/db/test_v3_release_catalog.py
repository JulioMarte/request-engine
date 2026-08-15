from typing import Any

import pytest
from psycopg import Connection

PgConnection = Connection[Any]
APPLICATION_SCHEMAS = ("request_engine", "request_read", "request_cmd", "request_admin")


@pytest.mark.postgres
def test_application_functions_are_not_executable_by_public(admin_conn: PgConnection) -> None:
    rows = admin_conn.execute(
        """
        SELECT n.nspname,
               p.proname,
               pg_get_function_identity_arguments(p.oid)
          FROM pg_proc p
          JOIN pg_namespace n ON n.oid = p.pronamespace
         WHERE n.nspname = ANY(%s)
           AND has_function_privilege('public', p.oid, 'EXECUTE')
         ORDER BY n.nspname, p.proname, pg_get_function_identity_arguments(p.oid)
        """,
        (list(APPLICATION_SCHEMAS),),
    ).fetchall()

    assert rows == []


@pytest.mark.postgres
def test_schema_owner_default_function_privileges_deny_public_execute(
    admin_conn: PgConnection,
) -> None:
    rows = admin_conn.execute(
        """
        SELECT n.nspname,
               a.privilege_type
          FROM pg_default_acl d
          JOIN pg_namespace n ON n.oid = d.defaclnamespace
          CROSS JOIN LATERAL aclexplode(d.defaclacl) a
         WHERE pg_get_userbyid(d.defaclrole) = 'request_engine_schema_owner'
           AND n.nspname = ANY(%s)
           AND d.defaclobjtype = 'f'
           AND a.grantee = 0
           AND a.privilege_type = 'EXECUTE'
         ORDER BY n.nspname
        """,
        (list(APPLICATION_SCHEMAS),),
    ).fetchall()

    assert rows == []
