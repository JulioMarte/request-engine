from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient

from request_engine.entrypoints.http.errors import (
    capability_required_handler,
    request_validation_error_handler,
)
from request_engine.modules.tenancy.api.party_registry_errors import (
    add_party_registry_error_handlers,
)
from request_engine.modules.tenancy.api.party_registry_routes import add_party_registry_routes
from request_engine.modules.tenancy.application.queries import lookup_parties
from request_engine.modules.tenancy.contracts.party_registry import (
    PartyContactPoint,
    PartyIdentityDocument,
    RegisteredParty,
)
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import CapabilityRequired


class _FixedActorResolver:
    def __init__(self, actor: ActorContext) -> None:
        self._actor = actor

    async def resolve_actor(self, request: Request) -> ActorContext:
        del request
        return self._actor


class _RecordingLookupReader:
    def __init__(self, parties: tuple[RegisteredParty, ...]) -> None:
        self.queries: list[lookup_parties.PartyLookupQuery] = []
        self._parties = parties

    async def lookup(self, query: lookup_parties.PartyLookupQuery) -> tuple[RegisteredParty, ...]:
        self.queries.append(query)
        return self._parties


def _looked_up_party() -> RegisteredParty:
    party_id = uuid4()
    return RegisteredParty(
        party_id=party_id,
        organization_id=uuid4(),
        party_kind="person",
        display_name="Jose Perez",
        active=True,
        contact_points=(PartyContactPoint(party_id, uuid4(), "phone", "+18295551234", True, None),),
        documents=(PartyIdentityDocument(party_id, uuid4(), "cedula", "40212345678"),),
    )


def _reader(parties: tuple[RegisteredParty, ...]) -> _RecordingLookupReader:
    return _RecordingLookupReader(parties)


def _app(actor: ActorContext, reader: lookup_parties.PartyLookupReader) -> FastAPI:
    unused: Any = object()
    router = APIRouter(prefix="/v1/parties")
    add_party_registry_routes(
        router,
        register_handler=unused,
        add_contact_point_handler=unused,
        confirm_handler=unused,
        lookup_reader=reader,
        actor_resolver=_FixedActorResolver(actor),
    )
    app = FastAPI()
    app.include_router(router)
    add_party_registry_error_handlers(app)
    app.add_exception_handler(CapabilityRequired, capability_required_handler)
    app.add_exception_handler(RequestValidationError, request_validation_error_handler)
    return app


def _actor() -> ActorContext:
    return ActorContext(
        organization_id=uuid4(), principal_id=uuid4(), capabilities=frozenset({"parties.lookup"})
    )


@pytest.mark.asyncio
async def test_phone_lookup_normalizes_term_and_returns_multi_match_shape() -> None:
    parties = (_looked_up_party(), _looked_up_party())
    reader = _reader(parties)
    async with AsyncClient(
        transport=ASGITransport(app=_app(_actor(), reader)), base_url="http://test"
    ) as client:
        response = await client.get(
            "/v1/parties/lookup", params={"mode": "phone", "value": "(809) 555-1234"}
        )

    assert response.status_code == 200, response.text
    assert reader.queries[0].mode is lookup_parties.PartyLookupMode.PHONE
    assert reader.queries[0].value == "+18095551234"
    body = cast(list[dict[str, Any]], response.json())
    assert len(body) == 2
    assert body[0]["party_id"] == str(parties[0].party_id)
    assert body[0]["contact_points"][0]["normalized_value"] == "+18295551234"
    assert body[0]["documents"][0]["kind"] == "cedula"


@pytest.mark.asyncio
async def test_document_lookup_maps_kind_and_normalized_value() -> None:
    reader = _reader(())
    async with AsyncClient(
        transport=ASGITransport(app=_app(_actor(), reader)), base_url="http://test"
    ) as client:
        response = await client.get(
            "/v1/parties/lookup",
            params={
                "mode": "document",
                "value": "ab1234567",
                "document_kind": "passport",
                "document_authority": "do",
            },
        )

    assert response.status_code == 200, response.text
    assert reader.queries[0].document_kind == "passport"
    assert reader.queries[0].document_authority == "DO"
    assert reader.queries[0].value == "AB1234567"


@pytest.mark.asyncio
async def test_lookup_requires_exactly_one_known_mode_and_a_value() -> None:
    reader = _reader(())
    async with AsyncClient(
        transport=ASGITransport(app=_app(_actor(), reader)), base_url="http://test"
    ) as client:
        bad_mode = await client.get(
            "/v1/parties/lookup", params={"mode": "email", "value": "someone@example.com"}
        )
        missing_value = await client.get("/v1/parties/lookup", params={"mode": "phone"})

    assert bad_mode.status_code == 422, bad_mode.text
    assert bad_mode.json()["error"]["code"] == "validation_failed"
    assert missing_value.status_code == 422, missing_value.text
    assert reader.queries == []
