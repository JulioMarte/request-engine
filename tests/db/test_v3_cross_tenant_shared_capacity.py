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
class Fixture:
    organization_id: UUID
    party_id: UUID
    offering_version_id: UUID
    requirement_id: UUID
    resource_id: UUID


def _uuid(conn: PgConnection, sql: LiteralString, params: tuple[object, ...]) -> UUID:
    row = conn.execute(sql, params).fetchone()
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
        (organization_id, f"visit-{suffix}", f"Visit {suffix}"),
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
        (organization_id, f"doctor-{suffix}", f"Doctor {suffix}"),
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
    return Fixture(
        organization_id,
        party_id,
        offering_version_id,
        requirement_id,
        resource_id,
    )


def _root(conn: PgConnection) -> UUID:
    identity_id = _uuid(
        conn,
        "SELECT request_admin.create_global_identity('person', NULL, %s, %s)",
        ("test.control-plane", "verified professional"),
    )
    return _uuid(
        conn,
        "SELECT request_admin.create_shared_capacity_identity(%s, %s, %s)",
        (identity_id, "test.control-plane", "serialize capacity"),
    )


def _bind(conn: PgConnection, fixture: Fixture, root_id: UUID) -> None:
    conn.execute(
        "SELECT request_admin.activate_shared_capacity_binding(%s, %s, %s, %s, %s)",
        (
            fixture.organization_id,
            fixture.resource_id,
            root_id,
            "test.control-plane",
            "verified binding",
        ),
    )


def _commitment(
    conn: PgConnection,
    fixture: Fixture,
    start: str,
    end: str,
) -> UUID:
    with conn.transaction():
        hold_id = _uuid(
            conn,
            """
            INSERT INTO request_engine.capacity_holds (
                organization_id, offering_version_id, subject_party_id, during, expires_at
            ) VALUES (
                %s, %s, %s, tstzrange(%s::timestamptz, %s::timestamptz, '[)'),
                clock_timestamp() + interval '1 hour'
            ) RETURNING id
            """,
            (
                fixture.organization_id,
                fixture.offering_version_id,
                fixture.party_id,
                start,
                end,
            ),
        )
        return _uuid(
            conn,
            """
            INSERT INTO request_engine.capacity_claims (
                organization_id, resource_id, requirement_id, hold_id, during, quantity
            ) VALUES (
                %s, %s, %s, %s,
                tstzrange(%s::timestamptz, %s::timestamptz, '[)'), 1
            ) RETURNING id
            """,
            (
                fixture.organization_id,
                fixture.resource_id,
                fixture.requirement_id,
                hold_id,
                start,
                end,
            ),
        )


def _set_app_context(conn: PgConnection, organization_id: UUID) -> None:
    conn.execute("SET ROLE request_engine_app")
    conn.execute(
        "SELECT set_config('request_engine.organization_id', %s, false)",
        (str(organization_id),),
    )


@pytest.mark.postgres
def test_global_shared_state_is_not_tenant_enumerable(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    tenant_a = _fixture(admin_conn, "privacy-a")
    tenant_b = _fixture(admin_conn, "privacy-b")
    root_id = _root(admin_conn)
    _bind(admin_conn, tenant_a, root_id)
    _bind(admin_conn, tenant_b, root_id)

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

        with pytest.raises(Error) as denied:
            app_conn.execute(
                "SELECT request_cmd.lock_shared_capacity_roots(%s, ARRAY[%s]::uuid[])",
                (tenant_a.organization_id, tenant_b.resource_id),
            )
        assert denied.value.sqlstate == "42501"
    finally:
        app_conn.close()


@pytest.mark.postgres
def test_cross_tenant_conflict_is_opaque_and_half_open(admin_conn: PgConnection) -> None:
    tenant_a = _fixture(admin_conn, "overlap-a")
    tenant_b = _fixture(admin_conn, "overlap-b")
    root_id = _root(admin_conn)
    _bind(admin_conn, tenant_a, root_id)
    _bind(admin_conn, tenant_b, root_id)
    start, end = "2030-01-01T14:00:00+00:00", "2030-01-01T14:30:00+00:00"
    claim_a = _commitment(admin_conn, tenant_a, start, end)

    with pytest.raises(Error) as conflict, admin_conn.transaction():
        _commitment(admin_conn, tenant_b, start, end)
    assert conflict.value.sqlstate == "23P01"
    message = str(conflict.value)
    assert "capacity unavailable" in message
    for secret in (
        tenant_a.organization_id,
        tenant_a.party_id,
        tenant_a.resource_id,
        claim_a,
        root_id,
    ):
        assert str(secret) not in message

    _commitment(
        admin_conn,
        tenant_b,
        "2030-01-01T14:30:00+00:00",
        "2030-01-01T15:00:00+00:00",
    )


@pytest.mark.postgres
@pytest.mark.concurrency
def test_simultaneous_cross_tenant_claims_have_exactly_one_winner(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    tenant_a = _fixture(admin_conn, "race-a")
    tenant_b = _fixture(admin_conn, "race-b")
    root_id = _root(admin_conn)
    _bind(admin_conn, tenant_a, root_id)
    _bind(admin_conn, tenant_b, root_id)
    start, end = "2030-02-01T14:00:00+00:00", "2030-02-01T14:30:00+00:00"
    barrier = threading.Barrier(2)
    results: list[str] = []
    result_lock = threading.Lock()

    def contender(fixture: Fixture) -> None:
        conn: PgConnection = psycopg.connect(pg_conninfo)
        outcome = "unexpected"
        try:
            _set_app_context(conn, fixture.organization_id)
            conn.commit()
            conn.execute("SET LOCAL lock_timeout = '5s'")
            conn.execute(
                """
                SELECT id FROM request_engine.resources
                WHERE organization_id = %s AND id = %s FOR UPDATE
                """,
                (fixture.organization_id, fixture.resource_id),
            ).fetchone()
            barrier.wait(timeout=5)
            conn.execute(
                "SELECT request_cmd.lock_shared_capacity_roots(%s, ARRAY[%s]::uuid[])",
                (fixture.organization_id, fixture.resource_id),
            ).fetchone()
            _commitment(conn, fixture, start, end)
            conn.commit()
            outcome = "won"
        except Error as exc:
            conn.rollback()
            if exc.sqlstate == "23P01" and "capacity unavailable" in str(exc):
                outcome = "unavailable"
            else:
                outcome = f"db-error:{exc.sqlstate}"
        except threading.BrokenBarrierError:
            conn.rollback()
            outcome = "barrier-broken"
        finally:
            conn.close()
            with result_lock:
                results.append(outcome)

    threads = [
        threading.Thread(target=contender, args=(tenant_a,), daemon=True),
        threading.Thread(target=contender, args=(tenant_b,), daemon=True),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert all(not thread.is_alive() for thread in threads)
    assert sorted(results) == ["unavailable", "won"]
