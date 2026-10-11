from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from request_engine.modules.communications.api.channel_policy_router import (
    create_channel_policy_router,
)
from request_engine.modules.communications.application.queries.channel_configuration import (
    ChannelConfiguration,
)
from request_engine.platform.security.context import ActorContext


@pytest.mark.asyncio
async def test_channel_configuration_is_typed_and_closes_filters_before_reader() -> None:
    current = ActorContext(
        organization_id=uuid4(),
        principal_id=uuid4(),
        capabilities=frozenset({"communications.read_configuration"}),
    )
    reader = AsyncMock()
    reader.read_configuration.return_value = ChannelConfiguration(
        "appointment_confirmation", False, 0, None, None
    )

    class Resolver:
        async def resolve_actor(self, request: object) -> ActorContext:
            return current

    app = FastAPI()
    app.include_router(
        create_channel_policy_router(
            handler=AsyncMock(),
            actor_resolver=Resolver(),
            reader=reader,
        )
    )
    path = "/v1/communications/channel-policies/appointment_confirmation"
    params = {"authority_party_id": str(uuid4())}
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        result = await client.get(path, params=params)
        assert result.status_code == 200
        assert result.headers["Cache-Control"] == "no-store"
        assert result.json() == {
            "purpose": "appointment_confirmation",
            "configured": False,
            "revision": 0,
            "enabled": None,
            "channel_policy": None,
        }
        query = reader.read_configuration.call_args.args[0]
        assert query.organization_id == current.organization_id
        reader.reset_mock()
        invalid = await client.get(path, params={**params, "organization_id": str(uuid4())})
        assert invalid.status_code == 422
        reader.read_configuration.assert_not_called()
    operation = app.openapi()["paths"][path.replace("appointment_confirmation", "{purpose}")]["get"]
    assert operation["x-request-engine-kind"] == "query"
    assert operation["x-request-engine-idempotency"] == "none"
