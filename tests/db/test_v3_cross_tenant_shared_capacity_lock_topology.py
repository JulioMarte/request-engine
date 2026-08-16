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
class TenantResources:
    organization_id: UUID
    resource_ids: tuple[UUID, UUID]


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...] = (),
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _tenant_with_two_resources(conn: PgConnection, label: str) -> TenantResources:
    suffix = f"{label}-{uuid4().hex}"
    organization_id = _uuid_row(
        conn,
        "INSERT INTO request_engine.organizations (organization_key, display_name) VALUES (%s, %s) RETURNING id",
        (suffix, suffix),
    )
    resource_ids = tuple(
        _uuid_row(
            conn,
            """
            INSERT INTO request_engine.resources (
                organization_id, resource_key, display_name, capacity_model, capacity_units
            ) VALUES (%s, %s, %s, 'exclusive', 1)
            RETURNING id
            """,
            (organization_id, f"resource-{ordinal}-{suffix}", f"Resource {ordinal} {suffix}"),
        )
        for ordinal in (1, 2)
    )
    return TenantResources(
        organization_id=organization_id,
        resource_ids=cast(tuple[UUID, UUID], resource_ids),
    )


def _shared_root(conn: PgConnection, label: str) -> UUID:
    identity_id = _uuid_row(
        conn,
        "SELECT request_admin.create_global_identity('person', NULL, %s, %s)",
        ("test.control-plane", f"identity {label}"),
    )
    return _uuid_row(
        conn,
        "SELECT request_admin.create_shared_capacity_identity(%s, %s, %s)",
        (identity_id, "test.control-plane", f"root {label}"),
    )


def _bind(conn: PgConnection, tenant: TenantResources, resource_id: UUID, root_id: UUID) -> None:
    conn.execute(
        "SELECT request_admin.activate_shared_capacity_binding(%s, %s, %s, %s, %s)",
        (
            tenant.organization_id,
            resource_id,
            root_id,
            "test.control-plane",
            "multi-root lock topology proof",
        ),
    )


def _set_app_context(conn: PgConnection, organization_id: UUID) -> None:
    conn.execute("SET ROLE request_engine_app")
    conn.execute(
        "SELECT set_config('request_engine.organization_id', %s, false)",
        (str(organization_id),),
    )
    conn.commit()


@pytest.mark.postgres
@pytest.mark.concurrency
def test_reversed_cross_tenant_multi_root_requests_do_not_deadlock(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    tenant_a = _tenant_with_two_resources(admin_conn, "lock-a")
    tenant_b = _tenant_with_two_resources(admin_conn, "lock-b")
    root_one = _shared_root(admin_conn, "one")
    root_two = _shared_root(admin_conn, "two")

    # Deliberately reverse the logical root mapping between tenants. If either
    # operation honored caller order rather than canonical row order, the two
    # transactions could form root_one -> root_two / root_two -> root_one.
    _bind(admin_conn, tenant_a, tenant_a.resource_ids[0], root_one)
    _bind(admin_conn, tenant_a, tenant_a.resource_ids[1], root_two)
    _bind(admin_conn, tenant_b, tenant_b.resource_ids[0], root_two)
    _bind(admin_conn, tenant_b, tenant_b.resource_ids[1], root_one)

    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    outcomes_lock = threading.Lock()

    def contender(tenant: TenantResources, requested_order: tuple[UUID, UUID]) -> None:
        conn: PgConnection = psycopg.connect(pg_conninfo)
        outcome = "unexpected"
        try:
            _set_app_context(conn, tenant.organization_id)
            conn.execute("SET LOCAL lock_timeout = '5s'")
            conn.execute(
                """
                SELECT id
                FROM request_engine.resources
                WHERE organization_id = %s
                  AND id = ANY(%s::uuid[])
                ORDER BY id
                FOR UPDATE
                """,
                (tenant.organization_id, list(requested_order)),
            ).fetchall()
            barrier.wait(timeout=5)
            conn.execute(
                "SELECT request_cmd.lock_shared_capacity_roots(%s, %s::uuid[])",
                (tenant.organization_id, list(requested_order)),
            ).fetchone()
            conn.execute("SELECT pg_sleep(0.05)").fetchone()
            conn.commit()
            outcome = "committed"
        except (Error, threading.BrokenBarrierError) as exc:
            conn.rollback()
            outcome = f"error:{exc}"
        finally:
            conn.close()
            with outcomes_lock:
                outcomes.append(outcome)

    threads = [
        threading.Thread(
            target=contender,
            args=(tenant_a, tenant_a.resource_ids),
            daemon=True,
        ),
        threading.Thread(
            target=contender,
            args=(tenant_b, tuple(reversed(tenant_b.resource_ids))),
            daemon=True,
        ),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert all(not thread.is_alive() for thread in threads), "multi-root lock topology deadlocked"
    assert sorted(outcomes) == ["committed", "committed"]
