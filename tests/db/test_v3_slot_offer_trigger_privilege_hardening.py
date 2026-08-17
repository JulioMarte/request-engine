from typing import Any

import pytest
from psycopg import Connection

PgConnection = Connection[Any]


@pytest.mark.postgres
def test_slot_offer_deferred_trigger_is_private_safe_security_definer(
    admin_conn: PgConnection,
) -> None:
    wrapper = admin_conn.execute(
        """
        SELECT p.prosecdef,
               pg_get_userbyid(p.proowner),
               p.proconfig,
               has_function_privilege(
                   'request_engine_app', p.oid, 'EXECUTE'
               ),
               has_function_privilege(
                   'request_engine_worker', p.oid, 'EXECUTE'
               ),
               has_function_privilege(
                   'request_engine_admin', p.oid, 'EXECUTE'
               ),
               has_function_privilege('public', p.oid, 'EXECUTE')
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'request_engine'
          AND p.proname = 'check_offered_slot_offer_source_consistency'
          AND oidvectortypes(p.proargtypes) = ''
        """
    ).fetchone()
    assert wrapper == (
        True,
        "request_engine_schema_owner",
        ["search_path=pg_catalog, request_engine, pg_temp"],
        False,
        False,
        False,
        False,
    )

    helper = admin_conn.execute(
        """
        SELECT p.prosecdef,
               pg_get_userbyid(p.proowner),
               has_function_privilege(
                   'request_engine_app', p.oid, 'EXECUTE'
               ),
               has_function_privilege(
                   'request_engine_worker', p.oid, 'EXECUTE'
               ),
               has_function_privilege(
                   'request_engine_admin', p.oid, 'EXECUTE'
               ),
               has_function_privilege('public', p.oid, 'EXECUTE')
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'request_engine'
          AND p.proname = 'assert_offered_slot_offer_source_consistency'
          AND oidvectortypes(p.proargtypes) = 'uuid, uuid'
        """
    ).fetchone()
    assert helper == (
        False,
        "request_engine_schema_owner",
        False,
        False,
        False,
        False,
    )
