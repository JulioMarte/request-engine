from __future__ import annotations

from dataclasses import dataclass
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection, Error

PgConnection = Connection[Any]
PRIVATE_TABLES = (
    "global_identities",
    "shared_capacity_identities",
    "shared_capacity_bindings",
    "shared_capacity_claim_links",
    "shared_capacity_authority_events",
)


@dataclass(frozen=True, slots=True)
class Fixture:
    organization_id: UUID
    party_id: UUID
    offering_version_id: UUID
    requirement_id: UUID
    resource_id: UUID


def _uuid(
    conn: PgConnection,
    statement: LiteralString,
    params: tuple[object, ...],
) -> UUID:
    row = conn.execute(statement, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _fixture(conn: PgConnection, label: str) -> Fixture:
    suffix = f"{label}-{uuid4().hex}"
    organization_id = _uuid(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s) RETURNING id
        """,
        (suffix, suffix),
    )
    party_id = _uuid(
        conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', %s) RETURNING id
        """,
        (organization_id, f"Party {suffix}"),
    )
    offering_id = _uuid(
        conn,
        """
        INSERT INTO request_engine.offerings (organization_id, offering_key, display_name)
        VALUES (%s, %s, %s) RETURNING id
        """,
        (organization_id, f"offering-{suffix}", f"Offering {suffix}"),
    )
    offering_version_id = _uuid(
        conn,
        """
        INSERT INTO request_engine.offering_versions (
            organization_id, offering_id, version, duration_minutes, bookable
        ) VALUES (%s, %s, 1, 30, true) RETURNING id
        """,
        (organization_id, offering_id),
    )
    capability_id = _uuid(
        conn,
        """
        INSERT INTO request_engine.resource_capabilities (
            organization_id, capability_key, display_name
        ) VALUES (%s, %s, %s) RETURNING id
        """,
        (organization_id, f"cap-{suffix}", f"Capability {suffix}"),
    )
    requirement_id = _uuid(
        conn,
        """
        INSERT INTO request_engine.offering_resource_requirements (
            organization_id, offering_version_id, capability_id, ordinal, quantity
        ) VALUES (%s, %s, %s, 1, 1) RETURNING id
        """,
        (organization_id, offering_version_id, capability_id),
    )
    resource_id = _uuid(
        conn,
        """
        INSERT INTO request_engine.resources (
            organization_id, resource_key, display_name, capacity_model, capacity_units
        ) VALUES (%s, %s, %s, 'exclusive', 1) RETURNING id
        """,
        (organization_id, f"resource-{suffix}", f"Resource {suffix}"),
    )
    conn.execute(
        """
        INSERT INTO request_engine.resource_capability_assignments (
            organization_id, resource_id, capability_id
        ) VALUES (%s, %s, %s)
        """,
        (organization_id, resource_id, capability_id),
    )
    return Fixture(
        organization_id=organization_id,
        party_id=party_id,
        offering_version_id=offering_version_id,
        requirement_id=requirement_id,
        resource_id=resource_id,
    )


def _root(conn: PgConnection, label: str) -> UUID:
    identity_id = _uuid(
        conn,
        "SELECT request_admin.create_global_identity('person', NULL, %s, %s)",
        ("test.control-plane", f"identity {label}"),
    )
    return _uuid(
        conn,
        "SELECT request_admin.create_shared_capacity_identity(%s, %s, %s)",
        (identity_id, "test.control-plane", f"root {label}"),
    )


def _bind(conn: PgConnection, fixture: Fixture, root_id: UUID) -> UUID:
    return _uuid(
        conn,
        "SELECT request_admin.activate_shared_capacity_binding(%s, %s, %s, %s, %s)",
        (
            fixture.organization_id,
            fixture.resource_id,
            root_id,
            "test.control-plane",
            "security hardening proof",
        ),
    )


def _live_hold_claim(conn: PgConnection, fixture: Fixture) -> tuple[UUID, UUID]:
    with conn.transaction():
        hold_id = _uuid(
            conn,
            """
            INSERT INTO request_engine.capacity_holds (
                organization_id, offering_version_id, subject_party_id, during, expires_at
            ) VALUES (
                %s, %s, %s,
                tstzrange('2030-06-01T14:00:00+00'::timestamptz,
                          '2030-06-01T14:30:00+00'::timestamptz, '[)'),
                clock_timestamp() + interval '1 hour'
            ) RETURNING id
            """,
            (fixture.organization_id, fixture.offering_version_id, fixture.party_id),
        )
        claim_id = _uuid(
            conn,
            """
            INSERT INTO request_engine.capacity_claims (
                organization_id, resource_id, requirement_id, hold_id, during, quantity
            ) VALUES (
                %s, %s, %s, %s,
                tstzrange('2030-06-01T14:00:00+00'::timestamptz,
                          '2030-06-01T14:30:00+00'::timestamptz, '[)'), 1
            ) RETURNING id
            """,
            (
                fixture.organization_id,
                fixture.resource_id,
                fixture.requirement_id,
                hold_id,
            ),
        )
    return hold_id, claim_id


@pytest.mark.postgres
def test_admin_private_shared_capacity_tables_are_read_only(admin_conn: PgConnection) -> None:
    rows = admin_conn.execute(
        """
        SELECT
            c.relname,
            has_table_privilege('request_engine_admin', c.oid, 'SELECT'),
            has_table_privilege('request_engine_admin', c.oid, 'INSERT'),
            has_table_privilege('request_engine_admin', c.oid, 'UPDATE'),
            has_table_privilege('request_engine_admin', c.oid, 'DELETE'),
            has_table_privilege('request_engine_admin', c.oid, 'TRUNCATE'),
            has_table_privilege('request_engine_admin', c.oid, 'REFERENCES'),
            has_table_privilege('request_engine_admin', c.oid, 'TRIGGER')
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'request_engine'
          AND c.relname = ANY(%s::text[])
        ORDER BY c.relname
        """,
        (list(PRIVATE_TABLES),),
    ).fetchall()

    assert len(rows) == len(PRIVATE_TABLES)
    for row in rows:
        assert cast(tuple[bool, ...], tuple(row[1:])) == (
            True,
            False,
            False,
            False,
            False,
            False,
            False,
        ), cast(str, row[0])

    function_privileges = admin_conn.execute(
        """
        SELECT
            has_function_privilege(
                'request_engine_admin',
                'request_admin.create_global_identity(text,text,text,text)',
                'EXECUTE'
            ),
            has_function_privilege(
                'request_engine_admin',
                'request_admin.create_shared_capacity_identity(uuid,text,text)',
                'EXECUTE'
            ),
            has_function_privilege(
                'request_engine_admin',
                'request_admin.activate_shared_capacity_binding(uuid,uuid,uuid,text,text)',
                'EXECUTE'
            ),
            has_function_privilege(
                'request_engine_admin',
                'request_admin.revoke_shared_capacity_binding(uuid,text,text)',
                'EXECUTE'
            )
        """
    ).fetchone()
    assert function_privileges == (True, True, True, True)


@pytest.mark.postgres
def test_runtime_root_lock_surface_locks_local_resource_itself(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    fixture = _fixture(admin_conn, "lock-surface")
    root_id = _root(admin_conn, "lock-surface")
    _bind(admin_conn, fixture, root_id)

    app_conn: PgConnection = psycopg.connect(pg_conninfo)
    observer: PgConnection = psycopg.connect(pg_conninfo)
    try:
        app_conn.execute("SET ROLE request_engine_app")
        app_conn.execute(
            "SELECT set_config('request_engine.organization_id', %s, false)",
            (str(fixture.organization_id),),
        )
        app_conn.commit()

        app_conn.execute(
            "SELECT request_cmd.lock_shared_capacity_roots(%s, ARRAY[%s]::uuid[])",
            (fixture.organization_id, fixture.resource_id),
        ).fetchone()

        with pytest.raises(Error) as blocked:
            observer.execute(
                """
                SELECT id FROM request_engine.resources
                WHERE organization_id = %s AND id = %s
                FOR UPDATE NOWAIT
                """,
                (fixture.organization_id, fixture.resource_id),
            ).fetchone()
        assert blocked.value.sqlstate == "55P03"
    finally:
        observer.rollback()
        app_conn.rollback()
        observer.close()
        app_conn.close()


@pytest.mark.postgres
def test_runtime_root_lock_surface_fails_closed_without_tenant_context(
    pg_conninfo: str,
) -> None:
    app_conn: PgConnection = psycopg.connect(pg_conninfo, autocommit=True)
    try:
        app_conn.execute("SET ROLE request_engine_app")
        with pytest.raises(Error) as denied:
            app_conn.execute(
                "SELECT request_cmd.lock_shared_capacity_roots(NULL, ARRAY[]::uuid[])"
            ).fetchone()
        assert denied.value.sqlstate == "42501"
    finally:
        app_conn.close()


@pytest.mark.postgres
def test_capacity_claim_definer_guard_cannot_oracle_foreign_rows(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    tenant_a = _fixture(admin_conn, "oracle-a")
    tenant_b = _fixture(admin_conn, "oracle-b")
    hold_id, _ = _live_hold_claim(admin_conn, tenant_b)

    app_conn: PgConnection = psycopg.connect(pg_conninfo, autocommit=True)
    try:
        app_conn.execute("SET ROLE request_engine_app")
        app_conn.execute(
            "SELECT set_config('request_engine.organization_id', %s, false)",
            (str(tenant_a.organization_id),),
        ).fetchone()

        outcomes: list[tuple[str | None, str]] = []
        for resource_id in (tenant_b.resource_id, uuid4()):
            with pytest.raises(Error) as denied:
                app_conn.execute(
                    """
                    INSERT INTO request_engine.capacity_claims (
                        organization_id, resource_id, requirement_id,
                        hold_id, during, quantity
                    ) VALUES (
                        %s, %s, %s, %s,
                        tstzrange('2030-06-01T14:00:00+00'::timestamptz,
                                  '2030-06-01T14:30:00+00'::timestamptz, '[)'), 1
                    )
                    """,
                    (
                        tenant_b.organization_id,
                        resource_id,
                        tenant_b.requirement_id,
                        hold_id,
                    ),
                )
            outcomes.append((denied.value.sqlstate, str(denied.value)))

        assert [sqlstate for sqlstate, _ in outcomes] == ["42501", "42501"]
        denied_message = "capacity claim organization context mismatch"
        assert all(denied_message in message for _, message in outcomes)
    finally:
        app_conn.close()


@pytest.mark.postgres
def test_linked_claim_cannot_resurrect_or_rewrite_historical_provenance(
    admin_conn: PgConnection,
) -> None:
    fixture = _fixture(admin_conn, "claim-history")
    root_id = _root(admin_conn, "claim-history")
    _bind(admin_conn, fixture, root_id)
    hold_id, claim_id = _live_hold_claim(admin_conn, fixture)

    with pytest.raises(Error) as resurrected, admin_conn.transaction():
        admin_conn.execute(
            """
            UPDATE request_engine.capacity_claims
            SET status = 'released', released_at = clock_timestamp()
            WHERE id = %s
            """,
            (claim_id,),
        )
        admin_conn.execute(
            """
            UPDATE request_engine.capacity_claims
            SET status = 'active', released_at = NULL
            WHERE id = %s
            """,
            (claim_id,),
        )
    assert resurrected.value.sqlstate == "23514"
    assert "terminal CapacityClaim" in str(resurrected.value)

    with admin_conn.transaction():
        admin_conn.execute(
            """
            UPDATE request_engine.capacity_claims
            SET status = 'released', released_at = clock_timestamp()
            WHERE id = %s
            """,
            (claim_id,),
        )
        admin_conn.execute(
            """
            UPDATE request_engine.capacity_holds
            SET status = 'released', revision = revision + 1
            WHERE id = %s
            """,
            (hold_id,),
        )

    with pytest.raises(Error) as rewritten:
        admin_conn.execute(
            """
            UPDATE request_engine.capacity_claims
            SET during = tstzrange(
                '2030-06-01T16:00:00+00'::timestamptz,
                '2030-06-01T16:30:00+00'::timestamptz,
                '[)'
            )
            WHERE id = %s
            """,
            (claim_id,),
        )
    assert rewritten.value.sqlstate == "55000"
    assert "material provenance is immutable" in str(rewritten.value)

    stored = admin_conn.execute(
        """
        SELECT c.status, lower(c.during), upper(c.during), link.shared_capacity_identity_id
        FROM request_engine.capacity_claims c
        JOIN request_engine.shared_capacity_claim_links link
          ON link.capacity_claim_id = c.id
        WHERE c.id = %s
        """,
        (claim_id,),
    ).fetchone()
    assert stored is not None
    assert stored[0] == "released"
    assert str(stored[1]) == "2030-06-01 14:00:00+00:00"
    assert str(stored[2]) == "2030-06-01 14:30:00+00:00"
    assert stored[3] == root_id


@pytest.mark.postgres
def test_promoted_claim_cannot_cross_hold_and_reservation_subjects(
    admin_conn: PgConnection,
) -> None:
    fixture = _fixture(admin_conn, "promotion-owner")
    root_id = _root(admin_conn, "promotion-owner")
    _bind(admin_conn, fixture, root_id)
    hold_id, claim_id = _live_hold_claim(admin_conn, fixture)
    other_party_id = _uuid(
        admin_conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', %s) RETURNING id
        """,
        (fixture.organization_id, "Different subject"),
    )

    reservation_id: UUID | None = None
    with pytest.raises(Error) as mismatch, admin_conn.transaction():
        reservation_id = _uuid(
            admin_conn,
            """
            INSERT INTO request_engine.reservations (
                organization_id, offering_version_id, subject_party_id, during
            ) VALUES (
                %s, %s, %s,
                tstzrange('2030-06-01T14:00:00+00'::timestamptz,
                          '2030-06-01T14:30:00+00'::timestamptz, '[)')
            ) RETURNING id
            """,
            (fixture.organization_id, fixture.offering_version_id, other_party_id),
        )
        admin_conn.execute(
            """
            UPDATE request_engine.capacity_claims
            SET reservation_id = %s
            WHERE id = %s AND status = 'active'
            """,
            (reservation_id, claim_id),
        )
    assert mismatch.value.sqlstate == "23514"
    assert "Hold/Reservation provenance mismatch" in str(mismatch.value)

    claim_owner = admin_conn.execute(
        "SELECT reservation_id FROM request_engine.capacity_claims WHERE id = %s",
        (claim_id,),
    ).fetchone()
    assert claim_owner == (None,)
    assert reservation_id is not None
    reservation_count = admin_conn.execute(
        "SELECT count(*) FROM request_engine.reservations WHERE id = %s",
        (reservation_id,),
    ).fetchone()
    assert reservation_count == (0,)
