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
        organization_id,
        party_id,
        offering_version_id,
        requirement_id,
        resource_id,
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
            "race proof",
        ),
    )


def _hold(conn: PgConnection, fixture: Fixture, start: str, end: str) -> UUID:
    return _uuid(
        conn,
        """
        INSERT INTO request_engine.capacity_holds (
            organization_id, offering_version_id, subject_party_id, during, expires_at
        ) VALUES (
            %s, %s, %s, tstzrange(%s::timestamptz, %s::timestamptz, '[)'),
            clock_timestamp() + interval '1 hour'
        ) RETURNING id
        """,
        (fixture.organization_id, fixture.offering_version_id, fixture.party_id, start, end),
    )


def _claim(conn: PgConnection, fixture: Fixture, hold_id: UUID, start: str, end: str) -> UUID:
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


def _claim_race(
    pg_conninfo: str,
    fixture: Fixture,
    start: str,
    end: str,
    barrier: threading.Barrier,
    output: list[UUID],
) -> None:
    conn: PgConnection = psycopg.connect(pg_conninfo)
    try:
        conn.execute("SET LOCAL lock_timeout = '5s'")
        conn.execute(
            """
            SELECT id FROM request_engine.resources
            WHERE organization_id = %s AND id = %s FOR UPDATE
            """,
            (fixture.organization_id, fixture.resource_id),
        ).fetchone()
        hold_id = _hold(conn, fixture, start, end)
        barrier.wait(timeout=5)
        output.append(_claim(conn, fixture, hold_id, start, end))
        conn.commit()
    finally:
        conn.close()


@pytest.mark.postgres
@pytest.mark.concurrency
def test_binding_activation_race_captures_live_commitment(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    fixture = _fixture(admin_conn, "activation")
    root_id = _root(admin_conn, "activation")
    start, end = "2030-03-01T14:00:00+00:00", "2030-03-01T14:30:00+00:00"
    barrier = threading.Barrier(2)
    claim_ids: list[UUID] = []
    errors: list[Exception] = []

    def activate() -> None:
        conn: PgConnection = psycopg.connect(pg_conninfo)
        try:
            barrier.wait(timeout=5)
            _bind(conn, fixture, root_id)
            conn.commit()
        except Exception as exc:  # pragma: no cover - asserted below
            conn.rollback()
            errors.append(exc)
        finally:
            conn.close()

    claim_thread = threading.Thread(
        target=lambda: _claim_race(pg_conninfo, fixture, start, end, barrier, claim_ids),
        daemon=True,
    )
    bind_thread = threading.Thread(target=activate, daemon=True)
    claim_thread.start()
    bind_thread.start()
    claim_thread.join(timeout=10)
    bind_thread.join(timeout=10)

    assert not claim_thread.is_alive() and not bind_thread.is_alive()
    assert not errors
    assert len(claim_ids) == 1
    assert admin_conn.execute(
        """
        SELECT shared_capacity_identity_id
        FROM request_engine.shared_capacity_claim_links
        WHERE capacity_claim_id = %s
        """,
        (claim_ids[0],),
    ).fetchone() == (root_id,)


@pytest.mark.postgres
@pytest.mark.concurrency
def test_binding_revocation_race_preserves_historical_link(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    fixture = _fixture(admin_conn, "revocation")
    root_id = _root(admin_conn, "revocation")
    binding_id = _bind(admin_conn, fixture, root_id)
    start, end = "2030-03-02T14:00:00+00:00", "2030-03-02T14:30:00+00:00"
    barrier = threading.Barrier(2)
    claim_ids: list[UUID] = []
    errors: list[Exception] = []

    def revoke() -> None:
        conn: PgConnection = psycopg.connect(pg_conninfo)
        try:
            barrier.wait(timeout=5)
            conn.execute(
                "SELECT request_admin.revoke_shared_capacity_binding(%s, %s, %s)",
                (binding_id, "test.control-plane", "concurrent revocation"),
            )
            conn.commit()
        except Exception as exc:  # pragma: no cover - asserted below
            conn.rollback()
            errors.append(exc)
        finally:
            conn.close()

    claim_thread = threading.Thread(
        target=lambda: _claim_race(pg_conninfo, fixture, start, end, barrier, claim_ids),
        daemon=True,
    )
    revoke_thread = threading.Thread(target=revoke, daemon=True)
    claim_thread.start()
    revoke_thread.start()
    claim_thread.join(timeout=10)
    revoke_thread.join(timeout=10)

    assert not claim_thread.is_alive() and not revoke_thread.is_alive()
    assert not errors
    assert len(claim_ids) == 1
    assert admin_conn.execute(
        """
        SELECT b.status, link.shared_capacity_identity_id
        FROM request_engine.shared_capacity_bindings b
        JOIN request_engine.shared_capacity_claim_links link
          ON link.capacity_claim_id = %s
        WHERE b.id = %s
        """,
        (claim_ids[0], binding_id),
    ).fetchone() == ("revoked", root_id)


@pytest.mark.postgres
def test_live_commitment_blocks_rebinding_to_different_root(admin_conn: PgConnection) -> None:
    fixture = _fixture(admin_conn, "rebind")
    first_root = _root(admin_conn, "first")
    second_root = _root(admin_conn, "second")
    binding_id = _bind(admin_conn, fixture, first_root)
    start, end = "2030-03-03T14:00:00+00:00", "2030-03-03T14:30:00+00:00"
    with admin_conn.transaction():
        hold_id = _hold(admin_conn, fixture, start, end)
        claim_id = _claim(admin_conn, fixture, hold_id, start, end)

    admin_conn.execute(
        "SELECT request_admin.revoke_shared_capacity_binding(%s, %s, %s)",
        (binding_id, "test.control-plane", "prepare rebinding test"),
    )
    with pytest.raises(Error) as rejected:
        _bind(admin_conn, fixture, second_root)
    assert rejected.value.sqlstate == "55000"
    assert "live commitments bound to another shared capacity root" in str(rejected.value)
    assert admin_conn.execute(
        """
        SELECT shared_capacity_identity_id
        FROM request_engine.shared_capacity_claim_links
        WHERE capacity_claim_id = %s
        """,
        (claim_id,),
    ).fetchone() == (first_root,)
