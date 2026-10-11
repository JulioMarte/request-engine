from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from request_engine.modules.delivery.api.resource_activity_routes import (
    create_resource_activity_router,
)
from request_engine.modules.delivery.contracts.service_session import (
    ResourceActivity,
    ResourceActivityKind,
)
from request_engine.platform.security.context import ActorContext


class Resolver:
    async def resolve_actor(self, request: Any) -> ActorContext:
        return ActorContext(
            organization_id=uuid4(),
            principal_id=uuid4(),
            capabilities=frozenset({"resource_activity.read"}),
        )


@pytest.mark.asyncio
@pytest.mark.adversarial
async def test_activity_history_is_bounded_and_rejects_invalid_filters() -> None:
    organization_id, resource_id = uuid4(), uuid4()
    now = datetime(2026, 10, 3, tzinfo=UTC)
    records = tuple(
        sorted(
            (
                ResourceActivity(
                    uuid4(), resource_id, None, ResourceActivityKind.BREAK, now, now, 2
                )
                for _ in range(3)
            ),
            key=lambda item: item.id,
            reverse=True,
        )
    )

    class StableResolver:
        async def resolve_actor(self, request: Any) -> ActorContext:
            return ActorContext(
                organization_id=organization_id,
                principal_id=uuid4(),
                capabilities=frozenset({"resource_activity.read"}),
            )

    class Reader:
        calls = 0

        async def list_for_resource(self, org: Any, resource: Any, **filters: Any) -> Any:
            self.calls += 1
            assert org == organization_id and resource == resource_id
            assert filters["limit"] == 3
            after_id = filters["after_id"]
            return tuple(item for item in records if after_id is None or item.id < after_id)[:3]

    reader = Reader()
    app = FastAPI()
    app.include_router(
        create_resource_activity_router(
            cast(Any, None),
            cast(Any, reader),
            StableResolver(),
        )
    )
    params = {"resource_id": str(resource_id), "active_only": False, "limit": 2}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.get("/resource-activities", params=params)
        assert first.status_code == 200, first.text
        second = await client.get(
            "/resource-activities",
            params={
                **params,
                "cursor": first.json()["next_cursor"],
            },
        )
        mismatch = await client.get(
            "/resource-activities",
            params={
                **params,
                "active_only": True,
                "cursor": first.json()["next_cursor"],
            },
        )
        unknown = await client.get("/resource-activities", params={**params, "tenant": "x"})
        invalid = await client.get("/resource-activities", params={**params, "cursor": "%%%"})
        naive = await client.get(
            "/resource-activities",
            params={
                **params,
                "started_after": "2026-10-01T00:00:00",
            },
        )
    assert second.status_code == 200
    assert second.json()["next_cursor"] is None
    ids = [item["id"] for page in (first, second) for item in page.json()["items"]]
    assert ids == [str(item.id) for item in records]
    assert (
        mismatch.status_code
        == unknown.status_code
        == invalid.status_code
        == naive.status_code
        == 422
    )
    assert reader.calls == 2
