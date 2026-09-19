from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from request_engine.modules.tenancy.api.self_authority import (
    create_self_authority_router,
    self_authority_error_handler,
)
from request_engine.modules.tenancy.application.queries.self_authority import (
    AuthorityInspectionDenied,
    SelfAuthorityQuery,
    SelfAuthoritySnapshot,
)
from request_engine.platform.security.context import ActorContext

pytestmark = [pytest.mark.unit, pytest.mark.security]


class _ActorResolver:
    def __init__(self, actor: ActorContext) -> None:
        self.actor = actor

    async def resolve_actor(self, request: Request) -> ActorContext:
        return self.actor


class _Reader:
    def __init__(self) -> None:
        self.calls: list[tuple[ActorContext, SelfAuthorityQuery]] = []
        self.denied = False

    async def read_self(
        self, actor: ActorContext, query: SelfAuthorityQuery
    ) -> SelfAuthoritySnapshot:
        self.calls.append((actor, query))
        if self.denied:
            raise AuthorityInspectionDenied("internal detail must not leak")
        return SelfAuthoritySnapshot(
            principal_id=actor.principal_id,
            authority_revision=7,
            observed_at=datetime(2026, 9, 13, tzinfo=UTC),
            representations=(),
            next_after=None,
        )


@pytest.mark.asyncio
async def test_self_authority_transport_is_typed_self_only_and_noncacheable() -> None:
    actor = ActorContext(uuid4(), uuid4(), frozenset({"authority.read_self"}))
    reader = _Reader()
    app = FastAPI()
    app.include_router(
        create_self_authority_router(reader=reader, actor_resolver=_ActorResolver(actor))
    )
    app.add_exception_handler(AuthorityInspectionDenied, self_authority_error_handler)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as client:
        response = await client.get("/v1/me/authority")
        assert response.status_code == 200
        assert response.json()["principal_id"] == str(actor.principal_id)
        assert response.json()["authority_revision"] == 7
        assert response.json()["requires_owner_validation"] is True
        assert response.headers["cache-control"] == "no-store"
        assert reader.calls == [(actor, SelfAuthorityQuery())]
        reader.denied = True
        denied = await client.get("/v1/me/authority")
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "authority_inspection_denied"
        assert "internal detail" not in denied.text
        assert denied.headers["cache-control"] == "no-store"
    operation = app.openapi()["paths"]["/v1/me/authority"]["get"]
    assert operation["operationId"] == "authority_read_self"
    assert operation["x-request-engine-owner"] == "tenancy"
    assert operation["x-request-engine-kind"] == "query"
    assert operation["x-request-engine-idempotency"] == "none"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        {"principal_id": str(uuid4())},
        {"organization_id": str(uuid4())},
        {"limit": "0"},
        {"limit": "101"},
        {"after": "not-a-uuid"},
    ],
)
async def test_self_authority_rejects_untrusted_selectors_and_invalid_pages(
    params: dict[str, str],
) -> None:
    actor = ActorContext(uuid4(), uuid4(), frozenset({"authority.read_self"}))
    reader = _Reader()
    app = FastAPI()
    app.include_router(
        create_self_authority_router(reader=reader, actor_resolver=_ActorResolver(actor))
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as client:
        response = await client.get("/v1/me/authority", params=params)
    assert response.status_code == 422
    assert reader.calls == []
