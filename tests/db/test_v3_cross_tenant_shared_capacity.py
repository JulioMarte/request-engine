from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection, Error

PgConnection = Connection[Any]


@dataclass(frozen=True, slots=True)
class CapacityFixture:
    organization_id: UUID
    party_id: UUID
    offering_version_id: UUID
    requirement_id: UUID
    resource_id: UUID


def _uuid_row(
    conn: PgConnection,
    query: LiteralString,
    params: tuple[object, ...],
) -> UUID:
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _create_capacity_fixture(conn: PgConnection, label: str) -> CapacityFixture:
    suffix = f"{label}-{uuid4().hex}"
    organization_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (suffix, suffix),
    )
    party_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', %s)
        RETURNING id
        """,
        (organization_id, f"Party {suffix}"),
    )
    capability_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.resource_capabilities (
            organization_id, capability_key, display_name
        ) VALUES (%s, %s, %s)
        RETURNING id
        """,
        (organization_id, f"doctor-{suffix}", f"Doctor {suffix}"),
    )
    offering_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offerings (
            organization_id, offering_key, display_name
        ) VALUES (%s, %s, %s)
        RETURNING id
        """,
        (organization_id, f"visit-{suffix}", f"Visit {suffix}"),
    )
    offering_version_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offering_versions (
            organization_id, offering_id, version, duration_minutes, bookable
        ) VALUES (%s, %s, 1, 30, true)
        RETURNING id
        """,
        (organization_id, offering_id),
    )
    requirement_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offering_resource_requirements (
            organization_id, offering_version_id, capability_id, ordinal, quantity
        ) VALUES (%s, %s, %s, 1, 1)
        RETURNING id
        """,
        (organization_id, offering_version_id, capability_id),
    )
    resource_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.resources (
            organization_id, resource_key, display_name, capacity_model, capacity_units
        ) VALUES (%s, %s, %s, 'exclusive', 1)
        RETURNING id
        """,
        (organization_id, f"provider-{suffix}", f"Provider {suffix}"),
    )
    conn.execute(
        """
        INSERT INTO request_engine.resource_capability_assignments (
            organization_id, resource_id, capability_id
        ) VALUES (%s, %s, %s)
        """,
        (organization_id, resource_id, capability_id),
    )
    return CapacityFixture(
        organization_id=organization_id,
        party_id=party_id,
        offering_version_id=offering_version_id,
        requirement_id=requirement_id,
        resource_id=resource_id,
    )


def _create_shared_root(conn: PgConnection) -> UUID:
    global_identity_id = _uuid_row(
        conn,
        "SELECT request_admin.create_global_identity('person', NULL, %s, %s)",
        ("test.control-plane", "verified shared professional"),
    )
    return _uuid_row(
        conn,
        "SELECT request_admin.create_shared_capacity_identity(%s, %s, %s)",
        (global_identity_id, "test.control-plane", "serialize professional capacity"),
    )


def _bind(conn: PgConnection, fixture: CapacityFixture, shared_root_id: UUID) -> UUID:
    return _uuid_row(
        conn,
        """
        SELECT request_admin.activate_shared_capacity_binding(%s, %s, %s, %s, %s)
        """,
        (
            fixture.organization_id,
            fixture.resource_id,
            shared_root_id,
            "test.control-plane",
            "verified tenant Resource binding",
        ),
    )


def _create_hold(
    conn: PgConnection,
    fixture: CapacityFixture,
    *,
    start_at: str,
    end_at: str,
) -> UUID:
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.capacity_holds (
            organization_id,
            offering_version_id,
            subject_party_id,
            during,
            expires_at
        ) VALUES (
            %s, %s, %s, tstzrange(%s::timestamptz, %s::timestamptz, '[)'),
            clock_timestamp() + interval '1 hour'
        )
        RETURNING id
        """,
        (
            fixture.organization_id,
            fixture.offering_version_id,
            fixture.party_id,
            start_at,
            end_at,
        ),
    )


def _insert_claim(
    conn: PgConnection,
    fixture: CapacityFixture,
    hold_id: UUID,
    *,
    start_at: str,
    end_at: str,
) -> UUID:
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.capacity_claims (
            organization_id,
            resource_id,
            requirement_id,
            hold_id,
            during,
            quantity
        ) VALUES (
            %s, %s, %s, %s,
            tstzrange(%s::timestamptz, %s::timestamptz, '[)'),
            1
        )
        RETURNING id
        """,
        (
            fixture.organization_id,
            fixture.resource_id,
            fixture.requirement_id,
            hold_id,
            start_at,
            end_at,
        ),
    )


def _set_app_context(conn: PgConnection, organization_id: UUID) -> None:
    conn.execute("SET ROLE request_engine_app")
    conn.execute(
        "SELECT set_config('request_engine.organization_id', %s, false)",
        (str(organization_id),),
    )


@pytest.mark.postgres
def test_shared_capacity_global_state_is_not_tenant_enumerable(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    tenant_a = _create_capacity_fixture(admin_conn, "privacy-a")
    tenant_b = _create_capacity_fixture(admin_conn, "privacy-b")
    shared_root_id = _create_shared_root(admin_conn)
    _bind(admin_conn, tenant_a, shared_root_id)
    _bind(admin_conn, tenant_b, shared_root_id)

    app_conn: PgConnection = psycopg.connect(pg_conninfo, autocommit=True)
    try:
        _set_app_context(app_conn, tenant_a.organization_id)
        for table_name in (
            "global_identities",
            "shared_capacity_identities",
            "shared_capacity_bindings",
            "shared_capacity_claim_links",
            "shared_capacity_authority_events",
        ):
            with pytest.raises(Error) as denied:
                app_conn.execute(f"SELECT count(*) FROM request_engine.{table_name}")
            assert denied.value.sqlstate == "42501"

        with pytest.raises(Error) as control_plane_denied:
            app_conn.execute(
                "SELECT request_admin.create_global_identity('person', NULL, 'attacker', 'probe')"
            )
        assert control_plane_denied.value.sqlstate == "42501"

        # Knowledge of a foreign Resource UUID is not a capability to reach its
        # shared root through the protected runtime lock surface.
        with pytest.raises(Error) as foreign_resource_denied:
            app_conn.execute(
                "SELECT request_cmd.lock_shared_capacity_roots(%s, ARRAY[%s]::uuid[])",
                (tenant_a.organization_id, tenant_b.resource_id),
            )
        assert foreign_resource_denied.value.sqlstate == "42501"
    finally:
        app_conn.close()


@pytest.mark.postgres
def test_cross_tenant_overlap_collapses_to_generic_capacity_unavailable(
    admin_conn: PgConnection,
) -> None:
    tenant_a = _create_capacity_fixture(admin_conn, "overlap-a")
    tenant_b = _create_capacity_fixture(admin_conn, "overlap-b")
    shared_root_id = _create_shared_root(admin_conn)
    _bind(admin_conn, tenant_a, shared_root_id)
    _bind(admin_conn, tenant_b, shared_root_id)

    start_at = "2030-01-01T14:00:00+00:00"
    end_at = "2030-01-01T14:30:00+00:00"
    hold_a = _create_hold(admin_conn, tenant_a, start_at=start_at, end_at=end_at)
    claim_a = _insert_claim(admin_conn, tenant_a, hold_a, start_at=start_at, end_at=end_at)

    linked_root = admin_conn.execute(
        """
        SELECT shared_capacity_identity_id
        FROM request_engine.shared_capacity_claim_links
        WHERE capacity_claim_id = %s
        """,
        (claim_a,),
    ).fetchone()
    assert linked_root == (shared_root_id,)

    hold_b = _create_hold(admin_conn, tenant_b, start_at=start_at, end_at=end_at)
    with pytest.raises(Error) as conflict:
        _insert_claim(admin_conn, tenant_b, hold_b, start_at=start_at, end_at=end_at)

    assert conflict.value.sqlstate == "23P01"
    message = str(conflict.value)
    assert "capacity unavailable" in message
    for secret in (
        str(tenant_a.organization_id),
        str(tenant_a.party_id),
        str(tenant_a.resource_id),
        str(claim_a),
        str(shared_root_id),
    ):
        assert secret not in message

    # The same foreign tenant can consume the same root at a non-overlapping
    # half-open interval, proving this is overlap serialization rather than a
    # blanket cross-tenant denial.
    later_start = "2030-01-01T14:30:00+00:00"
    later_end = "2030-01-01T15:00:00+00:00"
    later_hold = _create_hold(
        admin_conn,
        tenant_b,
        start_at=later_start,
        end_at=later_end,
    )
    _insert_claim(
        admin_conn,
        tenant_b,
        later_hold,
        start_at=later_start,
        end_at=later_end,
    )


@pytest.mark.postgres
def test_simultaneous_cross_tenant_claims_have_exactly_one_winner(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    tenant_a = _create_capacity_fixture(admin_conn, "race-a")
    tenant_b = _create_capacity_fixture(admin_conn, "race-b")
    shared_root_id = _create_shared_root(admin_conn)
    _bind(admin_conn, tenant_a, shared_root_id)
    _bind(admin_conn, tenant_b, shared_root_id)

    start_at = "2030-02-01T14:00:00+00:00"
    end_at = "2030-02-01T14:30:00+00:00"
    hold_a = _create_hold(admin_conn, tenant_a, start_at=start_at, end_at=end_at)
    hold_b = _create_hold(admin_conn, tenant_b, start_at=start_at, end_at=end_at)
    barrier = threading.Barrier(2)
    results: list[str] = []
    results_lock = threading.Lock()

    def contender(fixture: CapacityFixture, hold_id: UUID) -> None:
        conn: PgConnection = psycopg.connect(pg_conninfo)
        outcome = "unexpected"
        try:
            _set_app_context(conn, fixture.organization_id)
            conn.commit()
            conn.execute("SET LOCAL lock_timeout = '5s'")
            conn.execute(
                """
                SELECT id
                FROM request_engine.resources
                WHERE organization_id = %s AND id = %s
                FOR UPDATE
                """,
                (fixture.organization_id, fixture.resource_id),
            ).fetchone()
            barrier.wait(timeout=5)
            conn.execute(
                "SELECT request_cmd.lock_shared_capacity_roots(%s, ARRAY[%s]::uuid[])",
                (fixture.organization_id, fixture.resource_id),
            )
            _insert_claim(conn, fixture, hold_id, start_at=start_at, end_at=end_at)
            conn.commit()
            outcome = "won"
        except Error as exc:
            conn.rollback()
            if exc.sqlstate == "23P01" and "capacity unavailable" in str(exc):
                outcome = "unavailable"
            else:
                outcome = f"db-error:{exc.sqlstate}:{exc}"
        except threading.BrokenBarrierError:
            conn.rollback()
            outcome = "barrier-broken"
        finally:
            conn.close()
            with results_lock:
                results.append(outcome)

    threads = [
        threading.Thread(target=contender, args=(tenant_a, hold_a), daemon=True),
        threading.Thread(target=contender, args=(tenant_b, hold_b), daemon=True),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert all(not thread.is_alive() for thread in threads), "shared-capacity race deadlocked"
    assert sorted(results) == ["unavailable", "won"]

    live_linked_claims = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.shared_capacity_claim_links link
        JOIN request_engine.capacity_claims claim ON claim.id = link.capacity_claim_id
        LEFT JOIN request_engine.capacity_holds hold
          ON hold.organization_id = claim.organization_id
         AND hold.id = claim.hold_id
        WHERE link.shared_capacity_identity_id = %s
          AND claim.status = 'active'
          AND claim.during && tstzrange(%s::timestamptz, %s::timestamptz, '[)')
          AND hold.status = 'active'
          AND hold.expires_at > clock_timestamp()
        """,
        (shared_root_id, start_at, end_at),
    ).fetchone()
    assert live_linked_claims == (1,)
