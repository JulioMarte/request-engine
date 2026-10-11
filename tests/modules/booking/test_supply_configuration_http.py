from dataclasses import replace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from request_engine.modules.booking.api.supply_configuration_router import (
    create_supply_configuration_router,
)
from request_engine.modules.booking.application.queries.supply_configuration import (
    ResourceConfiguration,
)
from request_engine.platform.security.context import ActorContext


@pytest.mark.asyncio
async def test_resource_configuration_page_is_bounded_and_query_fields_are_closed() -> None:
    current = ActorContext(
        organization_id=uuid4(),
        principal_id=uuid4(),
        capabilities=frozenset({"booking.read_supply"}),
    )
    first = ResourceConfiguration(uuid4(), "room", "Room", "units", 2, True, 3, ())
    second = replace(first, resource_id=uuid4(), resource_key="room2")
    reader = AsyncMock()
    reader.read_resources.return_value = (first, second)

    class Resolver:
        async def resolve_actor(self, request: object) -> ActorContext:
            return current

    app = FastAPI()
    app.include_router(create_supply_configuration_router(reader=reader, actor_resolver=Resolver()))
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        params = {"authority_party_id": str(uuid4()), "limit": 1}
        response = await client.get("/v1/booking/resources", params=params)
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        assert len(response.json()["items"]) == 1
        assert response.json()["next_cursor"] == str(first.resource_id)
        sent = reader.read_resources.call_args.args[0]
        assert sent.organization_id == current.organization_id
        assert sent.principal_id == current.principal_id
        reader.read_resources.reset_mock()
        for field in ("organization_id", "location_id", "status"):
            invalid = await client.get(
                "/v1/booking/resources", params={**params, field: str(uuid4())}
            )
            assert invalid.status_code == 422
        reader.read_resources.assert_not_called()
    op = app.openapi()["paths"]["/v1/booking/resources"]["get"]
    assert op["x-request-engine-kind"] == "query"
    assert op["x-request-engine-idempotency"] == "none"
    assert "$ref" in op["responses"]["200"]["content"]["application/json"]["schema"]


@pytest.mark.asyncio
async def test_exact_final_page_does_not_advertise_continuation() -> None:
    current = ActorContext(
        organization_id=uuid4(),
        principal_id=uuid4(),
        capabilities=frozenset({"booking.read_supply"}),
    )
    reader = AsyncMock()
    reader.read_resources.return_value = (
        ResourceConfiguration(uuid4(), "room", "Room", "exclusive", 1, True, 1, ()),
    )

    class Resolver:
        async def resolve_actor(self, request: object) -> ActorContext:
            return current

    app = FastAPI()
    app.include_router(create_supply_configuration_router(reader=reader, actor_resolver=Resolver()))
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.get(
            "/v1/booking/resources", params={"authority_party_id": str(uuid4()), "limit": 1}
        )
    assert response.json()["next_cursor"] is None
