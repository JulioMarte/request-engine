"""Correction route command mapping: transport values pass verbatim into the
application commands and the responses map back from the affected views."""

from uuid import uuid4

import pytest
from fastapi import APIRouter, FastAPI, Request
from httpx import ASGITransport, AsyncClient

from request_engine.modules.tenancy.api.party_registry_correction_routes import (
    add_party_correction_routes,
)
from request_engine.modules.tenancy.api.party_registry_errors import (
    add_party_registry_error_handlers,
)
from request_engine.modules.tenancy.application.commands import (
    add_party_document,
    rename_party,
)
from request_engine.modules.tenancy.contracts.party_registry import (
    PartyIdentityDocument,
    RegisteredParty,
)
from request_engine.platform.security.context import ActorContext


class _FixedActorResolver:
    def __init__(self, actor: ActorContext) -> None:
        self._actor = actor

    async def resolve_actor(self, request: Request) -> ActorContext:
        del request
        return self._actor


class _RecordingCorrections:
    def __init__(self, party: RegisteredParty) -> None:
        self.renames: list[rename_party.RenamePartyCommand] = []
        self.documents: list[add_party_document.AddPartyDocumentCommand] = []
        self._party = party

    async def rename_party(self, command: rename_party.RenamePartyCommand) -> RegisteredParty:
        self.renames.append(command)
        return self._party

    async def add_party_document(
        self, command: add_party_document.AddPartyDocumentCommand
    ) -> PartyIdentityDocument:
        self.documents.append(command)
        return PartyIdentityDocument(command.party_id, uuid4(), command.kind, command.value)


def _party() -> RegisteredParty:
    return RegisteredParty(
        party_id=uuid4(),
        organization_id=uuid4(),
        party_kind="person",
        display_name="Jose Perez",
        active=True,
        contact_points=(),
        documents=(),
    )


def _actor(*capabilities: str) -> ActorContext:
    return ActorContext(
        organization_id=uuid4(), principal_id=uuid4(), capabilities=frozenset(capabilities)
    )


def _app(actor: ActorContext, commands: _RecordingCorrections) -> FastAPI:
    resolver = _FixedActorResolver(actor)
    router = APIRouter(prefix="/v1/parties")
    add_party_correction_routes(
        router,
        rename_handler=commands,
        add_document_handler=commands,
        authenticated_actor=resolver.resolve_actor,
    )
    app = FastAPI()
    app.include_router(router)
    add_party_registry_error_handlers(app)
    return app


async def _post(app: FastAPI, path: str, json_body: object, key: str):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(path, json=json_body, headers={"Idempotency-Key": key})


@pytest.mark.asyncio
async def test_rename_maps_body_verbatim_and_returns_the_party_view() -> None:
    party = _party()
    commands = _RecordingCorrections(party)
    response = await _post(
        _app(_actor("parties.rename"), commands),
        f"/v1/parties/{party.party_id}/rename",
        {"display_name": "Jose A Perez"},
        "rename-1",
    )

    assert response.status_code == 200, response.text
    command = commands.renames[0]
    assert (command.party_id, command.display_name) == (party.party_id, "Jose A Perez")
    assert response.json()["display_name"] == "Jose Perez"


@pytest.mark.asyncio
async def test_add_document_normalizes_like_register_and_maps_the_document_view() -> None:
    party = _party()
    commands = _RecordingCorrections(party)
    response = await _post(
        _app(_actor("parties.add_document"), commands),
        f"/v1/parties/{party.party_id}/documents",
        {"kind": "cedula", "value": "402-1234567-8"},
        "doc-1",
    )

    assert response.status_code == 201, response.text
    command = commands.documents[0]
    assert (command.kind, command.value) == ("cedula", "40212345678")
    assert response.json()["normalized_value"] == "40212345678"
