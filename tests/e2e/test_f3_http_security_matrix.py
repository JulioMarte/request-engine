from uuid import uuid4

import pytest
from fastapi import Request
from httpx import ASGITransport, AsyncClient

from request_engine.entrypoints.http.app import create_app
from request_engine.entrypoints.http.security import AuthenticationRequired
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

from . import operational_support as support
from .evidence import durable_snapshot
from .http_surface import PublicHttpOperation
from .http_surface_f3 import F3_HTTP_OPERATIONS

pytestmark = [pytest.mark.postgres, pytest.mark.e2e]
_SIGNING_KEY = b"request-engine-f3-security-signing-key"


class Resolver:
    def __init__(self, actor: ActorContext | None) -> None:
        self.actor = actor

    async def resolve_actor(self, request: Request) -> ActorContext:
        del request
        if self.actor is None:
            raise AuthenticationRequired
        return self.actor


async def _request(client: AsyncClient, operation: PublicHttpOperation):
    headers = {"Idempotency-Key": f"f3-security-{uuid4().hex}"}
    return await client.request(
        operation.method,
        operation.probe.path,
        params=dict(operation.probe.query),
        json=operation.probe.body,
        headers=headers if operation.idempotency_required else {},
    )


def _id(operation: PublicHttpOperation) -> str:
    return operation.name


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", F3_HTTP_OPERATIONS, ids=_id)
async def test_every_f3_operation_rejects_unauthenticated_without_mutation(
    operation: PublicHttpOperation,
    e2e_admin_conn: support.PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    before = durable_snapshot(e2e_admin_conn)
    app = create_app(
        session_factory=e2e_session_factory,
        actor_resolver=Resolver(None),
        appointment_option_signing_key=_SIGNING_KEY,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await _request(client, operation)
    assert response.status_code == 401, (operation.name, response.text)
    assert response.json()["error"]["code"] == "authentication_required"
    assert durable_snapshot(e2e_admin_conn) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", F3_HTTP_OPERATIONS, ids=_id)
async def test_every_f3_operation_rejects_missing_capability_without_mutation(
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
        actor_resolver=Resolver(actor),
        appointment_option_signing_key=_SIGNING_KEY,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await _request(client, operation)
    assert response.status_code == 403, (operation.name, response.text)
    assert response.json()["error"] == {
        "code": "capability_required",
        "message": "the authenticated actor lacks a required capability",
        "retryable": False,
        "resolution": "request_authority",
        "details": {"capability": operation.capability},
    }
    assert durable_snapshot(e2e_admin_conn) == before
