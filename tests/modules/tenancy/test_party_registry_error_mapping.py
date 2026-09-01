from typing import Any
from uuid import uuid4

import pytest
from fastapi import APIRouter, FastAPI, Request
from httpx import ASGITransport, AsyncClient

from request_engine.modules.tenancy.api.party_registry_errors import (
    add_party_registry_error_handlers,
)
from request_engine.modules.tenancy.api.party_registry_routes import add_party_registry_routes
from request_engine.modules.tenancy.application.commands import (
    add_party_contact_point,
    register_party,
)
from request_engine.modules.tenancy.application.errors import (
    PartyDocumentConflict,
    PartyNotFound,
)
from request_engine.modules.tenancy.contracts.party_registry import (
    PartyContactPoint,
    RegisteredParty,
)
from request_engine.platform.security.context import ActorContext


class _FixedActorResolver:
    def __init__(self, actor: ActorContext) -> None:
        self._actor = actor

    async def resolve_actor(self, request: Request) -> ActorContext:
        del request
        return self._actor


class _FailingRegistry:
    def __init__(self, error: Exception) -> None:
        self._error = error

    async def register_party(self, command: register_party.RegisterPartyCommand) -> RegisteredParty:
        raise self._error

    async def add_party_contact_point(
        self, command: add_party_contact_point.AddPartyContactPointCommand
    ) -> PartyContactPoint:
        raise self._error


def _actor() -> ActorContext:
    return ActorContext(
        organization_id=uuid4(),
        principal_id=uuid4(),
        capabilities=frozenset({"parties.register", "parties.add_contact_point"}),
    )


def _app(actor: ActorContext, failing: _FailingRegistry) -> FastAPI:
    unused: Any = object()
    router = APIRouter(prefix="/v1/parties")
    add_party_registry_routes(
        router,
        register_handler=failing,
        add_contact_point_handler=failing,
        confirm_handler=unused,
        lookup_reader=unused,
        actor_resolver=_FixedActorResolver(actor),
    )
    app = FastAPI()
    app.include_router(router)
    add_party_registry_error_handlers(app)
    return app


async def _post_register(failing: _FailingRegistry) -> tuple[int, dict[str, object]]:
    async with AsyncClient(
        transport=ASGITransport(app=_app(_actor(), failing)), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/parties",
            json={"display_name": "Jose Perez"},
            headers={"Idempotency-Key": f"error-mapping-{uuid4().hex}"},
        )
    return response.status_code, response.json()["error"]


async def _post_add_contact_point(failing: _FailingRegistry) -> tuple[int, dict[str, object]]:
    async with AsyncClient(
        transport=ASGITransport(app=_app(_actor(), failing)), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/v1/parties/{uuid4()}/contact-points",
            json={"channel": "phone", "value": "+18295551234"},
            headers={"Idempotency-Key": f"error-mapping-{uuid4().hex}"},
        )
    return response.status_code, response.json()["error"]


@pytest.mark.asyncio
async def test_document_conflict_maps_to_conflict_envelope() -> None:
    status, error = await _post_register(_FailingRegistry(PartyDocumentConflict("dup cedula")))
    assert status == 409
    assert error["code"] == "party_document_conflict"
    assert error["resolution"] == "fix_request"


@pytest.mark.asyncio
async def test_missing_party_maps_to_not_found_envelope() -> None:
    party_id = uuid4()
    status, error = await _post_add_contact_point(_FailingRegistry(PartyNotFound(party_id)))
    assert status == 404
    assert error["code"] == "party_not_found"
    assert error["details"] == {"party_id": str(party_id)}
