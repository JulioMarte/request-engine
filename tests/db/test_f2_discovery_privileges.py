from typing import Any

import pytest
from psycopg import Connection

PgConnection = Connection[Any]

_SEARCH = (
    "request_engine.search_discovery_candidates_v2("
    "text,double precision,double precision,integer,timestamptz,timestamptz,integer)"
)
_ISSUE = (
    "request_engine.issue_discovery_booking_handoff("
    "text,uuid,bigint,uuid,bigint,uuid,uuid,jsonb,timestamptz)"
)
_READ = "request_engine.read_discovery_booking_handoff(text)"


@pytest.mark.postgres
@pytest.mark.security
def test_discovery_runtime_role_is_non_login_and_non_bypass(admin_conn: PgConnection) -> None:
    row = admin_conn.execute(
        "SELECT rolcanlogin, rolbypassrls FROM pg_roles WHERE rolname = 'request_engine_discovery'"
    ).fetchone()
    assert row == (False, False)


@pytest.mark.postgres
@pytest.mark.security
def test_discovery_runtime_has_only_narrow_function_authority(admin_conn: PgConnection) -> None:
    row = admin_conn.execute(
        """
        SELECT
            has_function_privilege('request_engine_discovery', %s, 'EXECUTE'),
            has_function_privilege('request_engine_discovery', %s, 'EXECUTE'),
            has_function_privilege('request_engine_discovery', %s, 'EXECUTE'),
            has_function_privilege('request_engine_app', %s, 'EXECUTE'),
            has_function_privilege('request_engine_app', %s, 'EXECUTE'),
            has_function_privilege('request_engine_app', %s, 'EXECUTE')
        """,
        (_SEARCH, _ISSUE, _READ, _SEARCH, _ISSUE, _READ),
    ).fetchone()
    assert row == (True, True, False, False, False, True)


@pytest.mark.postgres
@pytest.mark.security
def test_discovery_runtime_has_no_direct_tenant_relation_privilege(
    admin_conn: PgConnection,
) -> None:
    relations = (
        "organizations",
        "locations",
        "offerings",
        "offering_versions",
        "resources",
        "resource_public_profiles",
        "service_classifications",
        "offering_service_classifications",
        "discovery_publications",
        "discovery_booking_handoffs",
        "reservations",
        "capacity_claims",
    )
    rows = admin_conn.execute(
        """
        SELECT relname, privilege
          FROM unnest(%s::text[]) relname
          CROSS JOIN unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE']) privilege
         WHERE has_table_privilege(
             'request_engine_discovery', 'request_engine.' || relname, privilege
         )
         ORDER BY relname, privilege
        """,
        (list(relations),),
    ).fetchall()
    assert rows == []


@pytest.mark.postgres
@pytest.mark.security
def test_app_cannot_enumerate_platform_taxonomy_directly(admin_conn: PgConnection) -> None:
    assert admin_conn.execute(
        """
        SELECT has_table_privilege(
            'request_engine_app', 'request_engine.service_classifications', 'SELECT'
        )
        """
    ).fetchone() == (False,)
    assert admin_conn.execute(
        """
        SELECT has_function_privilege(
            'request_engine_app',
            'request_engine.lookup_active_service_classification(text)',
            'EXECUTE'
        )
        """
    ).fetchone() == (True,)
