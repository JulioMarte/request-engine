# Shared world/inspection helpers for the F5 fallback sweep PostgreSQL proofs.

from __future__ import annotations

from uuid import UUID

from e2e.f5_recovery_support import f5_actor
from e2e.f5_recovery_world import prepare_recovery_world
from e2e.operational_support import PgConnection
from e2e.tenant_sandbox import TenantSandbox, client_with_actors, seed_tenant_sandbox
from request_engine.platform.db.session import SessionFactory


async def sweep_world(
    admin_conn: PgConnection, session_factory: SessionFactory, label: str
) -> TenantSandbox:
    sandbox = seed_tenant_sandbox(admin_conn, label)
    async with client_with_actors(session_factory, {sandbox.token: f5_actor(sandbox)}) as client:
        await prepare_recovery_world(client, admin_conn, sandbox)
    return sandbox


def sweep_action_row(conn: PgConnection, org: UUID, key: str) -> tuple[object, ...] | None:
    row = conn.execute(
        "SELECT owner_module,action_type,action_version,subject_kind,subject_id,payload,"
        "status,max_attempts FROM request_engine.scheduled_actions "
        "WHERE organization_id=%s AND dedupe_key=%s",
        (org, key),
    ).fetchone()
    return tuple(row) if row else None


def delete_sweep_action(conn: PgConnection, sandbox: TenantSandbox, revision: int) -> None:
    conn.execute(
        "DELETE FROM request_engine.scheduled_actions WHERE organization_id=%s AND dedupe_key=%s",
        (sandbox.organization_id, f"f5-reassessment:{sandbox.queue_id}:{revision}"),
    )
