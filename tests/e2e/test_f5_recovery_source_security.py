from uuid import UUID

import psycopg
import pytest

from request_engine.platform.db.session import SessionFactory

from .f5_recovery_support import f5_actor
from .f5_recovery_world import prepare_recovery_world
from .operational_support import PgConnection, RuntimeCredentialsLike, runtime_conn
from .tenant_sandbox import client_with_actors, seed_tenant_sandbox

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.invariant,
    pytest.mark.contract,
    pytest.mark.adversarial,
    pytest.mark.security,
]


async def test_f5_recovery_source_security_definer_paths_remain_tenant_scoped(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
    app_runtime_credentials: RuntimeCredentialsLike,
) -> None:
    tenant_a = seed_tenant_sandbox(e2e_admin_conn, "f5-source-rls-a")
    tenant_b = seed_tenant_sandbox(e2e_admin_conn, "f5-source-rls-b")
    actors = {
        tenant_a.token: f5_actor(tenant_a),
        tenant_b.token: f5_actor(tenant_b),
    }

    async with client_with_actors(e2e_session_factory, actors) as client:
        await prepare_recovery_world(client, e2e_admin_conn, tenant_a)
        await prepare_recovery_world(client, e2e_admin_conn, tenant_b)

    with runtime_conn(app_runtime_credentials) as conn:
        conn.execute("BEGIN")
        try:
            conn.execute(
                "SELECT set_config('request_engine.organization_id', %s, true)",
                (str(tenant_a.organization_id),),
            )

            own_row = conn.execute(
                "SELECT request_read.recovery_source_revision(%s, %s)",
                (tenant_a.organization_id, tenant_a.queue_id),
            ).fetchone()
            assert own_row is not None
            assert isinstance(own_row[0], int)

            other_row = conn.execute(
                "SELECT request_read.recovery_source_revision(%s, %s)",
                (tenant_b.organization_id, tenant_b.queue_id),
            ).fetchone()
            assert other_row == (None,)

            with pytest.raises(psycopg.errors.CheckViolation):
                conn.execute(
                    "SELECT request_cmd.lock_recovery_source_revision(%s, %s)",
                    (tenant_b.organization_id, tenant_b.queue_id),
                ).fetchone()
        finally:
            conn.rollback()

    admin_rows = e2e_admin_conn.execute(
        """
        SELECT organization_id, service_queue_id
        FROM request_engine.recovery_source_revisions
        WHERE (organization_id, service_queue_id) IN ((%s, %s), (%s, %s))
        """,
        (
            tenant_a.organization_id,
            tenant_a.queue_id,
            tenant_b.organization_id,
            tenant_b.queue_id,
        ),
    ).fetchall()
    assert {(UUID(str(row[0])), UUID(str(row[1]))) for row in admin_rows} == {
        (tenant_a.organization_id, tenant_a.queue_id),
        (tenant_b.organization_id, tenant_b.queue_id),
    }
