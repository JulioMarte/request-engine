import asyncio
from uuid import UUID, uuid4

import pytest
from fastapi import Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from request_engine.entrypoints.http.app import create_app
from request_engine.entrypoints.http.capabilities import CapabilityCatalogView
from request_engine.platform.db.session import create_postgres_engine, create_session_factory
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.discovery import TenantCapabilityPolicy


class StaticActorResolver:
    def __init__(self, actor: ActorContext) -> None:
        self._actor = actor

    async def resolve_actor(self, request: Request) -> ActorContext:
        del request
        return self._actor


class StaticTenantPolicy(TenantCapabilityPolicy):
    def __init__(self, enabled: frozenset[str]) -> None:
        self._enabled = enabled

    async def enabled_capabilities(self, organization_id: UUID) -> frozenset[str]:
        del organization_id
        return self._enabled


def _client(*, actor: ActorContext, enabled: frozenset[str]) -> tuple[AsyncClient, AsyncEngine]:
    engine = create_postgres_engine("postgresql+asyncpg://user:pass@127.0.0.1/request_engine")
    app = create_app(
        session_factory=create_session_factory(engine),
        actor_resolver=StaticActorResolver(actor),
        appointment_option_signing_key=b"phase-5-http-policy-test-key",
        tenant_capability_policy=StaticTenantPolicy(enabled),
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test"), engine


@pytest.mark.asyncio
async def test_discovery_keeps_actor_grant_separate_from_tenant_enablement() -> None:
    actor = ActorContext(
        organization_id=uuid4(),
        principal_id=uuid4(),
        capabilities=frozenset({"business.get_info"}),
    )
    client, engine = _client(actor=actor, enabled=frozenset())
    try:
        async with client:
            response = await client.get("/v1/capabilities")
        assert response.status_code == 200
        catalog = CapabilityCatalogView.model_validate(response.json())
        business = next(item for item in catalog.capabilities if item.key == "business.get_info")
        assert business.product_supported is True
        assert business.actor_granted is True
        assert business.tenant_enabled is False
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_tenant_disabled_capability_cannot_execute_even_when_actor_has_grant() -> None:
    actor = ActorContext(
        organization_id=uuid4(),
        principal_id=uuid4(),
        capabilities=frozenset({"business.get_info"}),
    )
    client, engine = _client(actor=actor, enabled=frozenset())
    try:
        async with client:
            response = await client.get("/v1/business")
        assert response.status_code == 403
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_tenant_enabled_capability_cannot_execute_without_actor_grant() -> None:
    actor = ActorContext(
        organization_id=uuid4(),
        principal_id=uuid4(),
        capabilities=frozenset(),
    )
    client, engine = _client(actor=actor, enabled=frozenset({"business.get_info"}))
    try:
        async with client:
            response = await client.get("/v1/business")
        assert response.status_code == 403
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_server_generates_distinct_request_correlation_and_ignores_caller_value() -> None:
    actor = ActorContext(
        organization_id=uuid4(),
        principal_id=uuid4(),
        capabilities=frozenset(),
    )
    client, engine = _client(actor=actor, enabled=frozenset())
    try:
        supplied = str(uuid4())
        async with client:
            first = await client.get("/v1/capabilities", headers={"X-Correlation-ID": supplied})
            second = await client.get("/v1/capabilities")
        assert first.status_code == 200
        assert second.status_code == 200
        first_id = first.headers["X-Correlation-ID"]
        second_id = second.headers["X-Correlation-ID"]
        assert UUID(first_id)
        assert UUID(second_id)
        assert first_id != supplied
        assert first_id != second_id
    finally:
        await engine.dispose()
