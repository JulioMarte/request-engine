from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient, Response

from request_engine.platform.db.session import SessionFactory

from . import operational_support as support
from .evidence import durable_snapshot
from .http_isolation_probes import (
    ForeignObjects,
    isolation_actor,
)
from .http_isolation_probes import (
    foreign_request as _foreign_request,
)
from .http_isolation_world import seed_foreign_objects
from .http_surface import PublicHttpOperation, TenantIsolationMode
from .http_surface_current import MATRIX_OPERATIONS
from .tenant_sandbox import (
    TenantSandbox,
    auth,
    client_with_actors,
    seed_tenant_sandbox,
)

pytestmark = [pytest.mark.postgres, pytest.mark.e2e]


async def _invoke(
    client: AsyncClient,
    operation: PublicHttpOperation,
    actor: TenantSandbox,
    foreign: TenantSandbox,
    objects: ForeignObjects,
) -> tuple[Response, int]:
    path, query, body, expected = _foreign_request(operation, actor, foreign, objects)
    headers = auth(
        actor,
        idempotency_key=f"cross-{operation.name}-{uuid4().hex}"
        if operation.idempotency_required
        else None,
    )
    response = await client.request(
        operation.method, path, params=query, json=body, headers=headers
    )
    return response, expected


def _test_id(operation: PublicHttpOperation) -> str:
    return operation.name


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", MATRIX_OPERATIONS, ids=_test_id)
async def test_every_public_operation_enforces_tenant_or_party_boundary_without_mutation(
    operation: PublicHttpOperation,
    e2e_admin_conn: support.PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    tenant_a = seed_tenant_sandbox(e2e_admin_conn, "tenant-a")
    tenant_b = seed_tenant_sandbox(e2e_admin_conn, "tenant-b")
    actors = {
        tenant_a.token: isolation_actor(tenant_a, allow_overrides=False),
        tenant_b.token: isolation_actor(tenant_b, allow_overrides=True),
    }
    async with client_with_actors(e2e_session_factory, actors) as client:
        objects = await seed_foreign_objects(client, e2e_admin_conn, tenant_a, tenant_b)
        before = durable_snapshot(e2e_admin_conn)
        response, expected = await _invoke(client, operation, tenant_a, tenant_b, objects)
    assert response.status_code == expected, (operation.name, response.text)
    if operation.tenant_isolation in {TenantIsolationMode.FILTERED, TenantIsolationMode.CONTEXTUAL}:
        assert tenant_b.organization_key not in response.text
        assert tenant_b.display_name not in response.text
        assert tenant_b.offering_key not in response.text
        assert str(tenant_b.queue_id) not in response.text
    assert durable_snapshot(e2e_admin_conn) == before
