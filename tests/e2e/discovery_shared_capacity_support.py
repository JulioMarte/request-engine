from __future__ import annotations

from typing import cast
from uuid import UUID

from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox


def create_shared_root(conn: PgConnection) -> UUID:
    global_row = conn.execute(
        "SELECT request_admin.create_global_identity('person', NULL, %s, %s)",
        ("f2-e2e.control-plane", "shared discovery professional"),
    ).fetchone()
    assert global_row is not None
    root_row = conn.execute(
        "SELECT request_admin.create_shared_capacity_identity(%s, %s, %s)",
        (
            cast(UUID, global_row[0]),
            "f2-e2e.control-plane",
            "serialize discovery booking capacity",
        ),
    ).fetchone()
    assert root_row is not None
    return cast(UUID, root_row[0])


def bind_shared_root(conn: PgConnection, sandbox: TenantSandbox, root_id: UUID) -> None:
    row = conn.execute(
        "SELECT request_admin.activate_shared_capacity_binding(%s, %s, %s, %s, %s)",
        (
            sandbox.organization_id,
            sandbox.resource_id,
            root_id,
            "f2-e2e.control-plane",
            "verified discovery Resource binding",
        ),
    ).fetchone()
    assert row is not None
