from typing import Any

import pytest
from psycopg import Connection

PgConnection = Connection[Any]

_F1_TABLES = (
    "organization_public_contact_endpoints",
    "location_public_contact_endpoints",
    "location_operational_hours",
    "location_hours_exceptions",
    "resource_location_assignments",
    "resource_location_availability",
    "resource_location_schedule_exceptions",
    "offering_version_booking_terms",
    "booking_context_terms",
    "reservation_commercial_commitments",
    "reservation_commercial_commitment_context_terms",
)

_F1_HELPERS = (
    "guard_location_operational_revision",
    "bump_location_operational_revision_from_child",
    "guard_resource_location_assignment",
    "bump_resource_from_assignment",
    "bump_resource_from_assignment_child",
    "guard_booking_context_terms_scope",
    "lock_booking_context_terms_resource",
    "lock_offering_version_booking_terms_root",
    "guard_capacity_claim_contextual_assignment",
    "guard_exact_revision_step",
)


@pytest.mark.postgres
def test_f1_internal_helpers_are_not_publicly_executable(admin_conn: PgConnection) -> None:
    rows = admin_conn.execute(
        """
        SELECT p.proname
          FROM pg_proc p
          JOIN pg_namespace n ON n.oid = p.pronamespace
         WHERE n.nspname = 'request_engine'
           AND p.proname = ANY(%s::text[])
           AND has_function_privilege('public', p.oid, 'EXECUTE')
         ORDER BY p.proname
        """,
        (list(_F1_HELPERS),),
    ).fetchall()

    assert rows == []


@pytest.mark.postgres
def test_app_can_replace_assignment_availability_under_rls(admin_conn: PgConnection) -> None:
    row = admin_conn.execute(
        """
        SELECT has_table_privilege(
            'request_engine_app',
            'request_engine.resource_location_availability',
            'SELECT,INSERT,UPDATE,DELETE'
        )
        """
    ).fetchone()
    assert row == (True,)


@pytest.mark.postgres
def test_worker_has_no_direct_f1_authoritative_relation_privileges(
    admin_conn: PgConnection,
) -> None:
    rows = admin_conn.execute(
        """
        SELECT c.relname, privilege.privilege_type
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
          CROSS JOIN LATERAL aclexplode(COALESCE(c.relacl, acldefault('r', c.relowner))) privilege
         WHERE n.nspname = 'request_engine'
           AND c.relname = ANY(%s::text[])
           AND privilege.grantee = (
               SELECT oid FROM pg_roles WHERE rolname = 'request_engine_worker'
           )
         ORDER BY c.relname, privilege.privilege_type
        """,
        (list(_F1_TABLES),),
    ).fetchall()

    assert rows == []


@pytest.mark.postgres
def test_f1_revisioned_aggregates_use_canonical_exact_revision_guard(
    admin_conn: PgConnection,
) -> None:
    rows = admin_conn.execute(
        """
        SELECT c.relname, p.proname
          FROM pg_trigger t
          JOIN pg_class c ON c.oid = t.tgrelid
          JOIN pg_namespace n ON n.oid = c.relnamespace
          JOIN pg_proc p ON p.oid = t.tgfoid
         WHERE n.nspname = 'request_engine'
           AND c.relname IN ('resource_location_assignments', 'booking_context_terms')
           AND NOT t.tgisinternal
           AND p.proname = 'guard_exact_revision_step'
         ORDER BY c.relname, p.proname
        """
    ).fetchall()

    assert rows == [
        ("booking_context_terms", "guard_exact_revision_step"),
        ("resource_location_assignments", "guard_exact_revision_step"),
    ]
