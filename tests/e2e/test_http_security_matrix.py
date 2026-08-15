from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import Request
from httpx import ASGITransport, AsyncClient, Response

from request_engine.entrypoints.http.app import create_app
from request_engine.entrypoints.http.security import AuthenticationRequired
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

from . import operational_support as support
from .evidence import durable_snapshot
from .http_surface import PUBLIC_HTTP_OPERATIONS, PublicHttpOperation

pytestmark = [pytest.mark.postgres, pytest.mark.e2e]


class SecurityProbeResolver:
    def __init__(self, actor: ActorContext | None) -> None:
        self._actor = actor

    async def resolve_actor(self, request: Request) -> ActorContext:
        del request
        if self._actor is None:
            raise AuthenticationRequired
        return self._actor


def _headers(operation: PublicHttpOperation) -> dict[str, str]:
    if operation.idempotency_required:
        return {"Idempotency-Key": f"security-probe-{uuid4().hex}"}
    return {}


async def _request(client: AsyncClient, operation: PublicHttpOperation) -> Response:
    return await client.request(
        operation.method,
        operation.probe.path,
        params=dict(operation.probe.query),
        json=operation.probe.body,
        headers=_headers(operation),
    )


def _test_id(operation: PublicHttpOperation) -> str:
    return operation.name


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", PUBLIC_HTTP_OPERATIONS, ids=_test_id)
async def test_every_public_operation_rejects_unauthenticated_requests_without_mutation(
    operation: PublicHttpOperation,
    e2e_admin_conn: support.PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    before = durable_snapshot(e2e_admin_conn)
    app = create_app(
        session_factory=e2e_session_factory,
        actor_resolver=SecurityProbeResolver(None),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await _request(client, operation)

    assert response.status_code == 401, (operation.name, response.text)
    assert response.json() == {"detail": "authentication required"}
    assert durable_snapshot(e2e_admin_conn) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", PUBLIC_HTTP_OPERATIONS, ids=_test_id)
async def test_every_public_operation_requires_its_declared_capability_without_mutation(
    operation: PublicHttpOperation,
    e2e_admin_conn: support.PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    actor = ActorContext(
        organization_id=uuid4(),
        principal_id=uuid4(),
        capabilities=frozenset(),
    )
    before = durable_snapshot(e2e_admin_conn)
    app = create_app(
        session_factory=e2e_session_factory,
        actor_resolver=SecurityProbeResolver(actor),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await _request(client, operation)

    assert response.status_code == 403, (operation.name, response.text)
    assert response.json() == {
        "detail": f"capability {operation.capability!r} is required"
    }
    assert durable_snapshot(e2e_admin_conn) == before
