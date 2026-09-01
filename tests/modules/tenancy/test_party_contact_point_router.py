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
    confirm_party_contact_point,
)
from request_engine.modules.tenancy.contracts.party_registry import (
    PartyContactPoint,
    RegisteredVia,
)
from request_engine.platform.security.context import ActorContext


class _FixedActorResolver:
    def __init__(self, actor: ActorContext) -> None:
        self._actor = actor

    async def resolve_actor(self, request: Request) -> ActorContext:
        del request
        return self._actor


class _RecordingContactPointCommands:
    def __init__(self, contact_point: PartyContactPoint) -> None:
        self.add_commands: list[add_party_contact_point.AddPartyContactPointCommand] = []
        self.confirm_commands: list[
            confirm_party_contact_point.ConfirmPartyContactPointCommand
        ] = []
        self._contact_point = contact_point

    async def add_party_contact_point(
        self, command: add_party_contact_point.AddPartyContactPointCommand
    ) -> PartyContactPoint:
        self.add_commands.append(command)
        return self._contact_point

    async def confirm_party_contact_point(
        self, command: confirm_party_contact_point.ConfirmPartyContactPointCommand
    ) -> PartyContactPoint:
        self.confirm_commands.append(command)
        return self._contact_point


def _bot_contact_point() -> PartyContactPoint:
    return PartyContactPoint(
        party_id=uuid4(),
        contact_point_id=uuid4(),
        channel="whatsapp",
        normalized_value="+18095551234",
        verified=False,
        registered_via=RegisteredVia.BOT,
    )


def _app(actor: ActorContext, commands: _RecordingContactPointCommands) -> FastAPI:
    unused: Any = object()
    router = APIRouter(prefix="/v1/parties")
    add_party_registry_routes(
        router,
        register_handler=unused,
        add_contact_point_handler=commands,
        confirm_handler=commands,
        lookup_reader=unused,
        actor_resolver=_FixedActorResolver(actor),
    )
    app = FastAPI()
    app.include_router(router)
    add_party_registry_error_handlers(app)
    return app


def _actor(*capabilities: str) -> ActorContext:
    return ActorContext(
        organization_id=uuid4(), principal_id=uuid4(), capabilities=frozenset(capabilities)
    )


@pytest.mark.asyncio
async def test_add_contact_point_derives_bot_attribution_and_maps_view() -> None:
    commands = _RecordingContactPointCommands(_bot_contact_point())
    actor = _actor("parties.add_contact_point")
    async with AsyncClient(
        transport=ASGITransport(app=_app(actor, commands)), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/parties/00000000-0000-4000-8000-000000000001/contact-points",
            json={"channel": "whatsapp", "value": "(809) 555-1234"},
            headers={"Idempotency-Key": "add-contact-bot"},
        )

    assert response.status_code == 201, response.text
    command = commands.add_commands[0]
    assert command.registered_via is RegisteredVia.BOT
    body = response.json()
    assert body["verified"] is False
    assert body["registered_via"] == "bot"
    assert body["normalized_value"] == "+18095551234"


@pytest.mark.asyncio
async def test_confirm_contact_point_maps_command_and_returns_view() -> None:
    contact_point = _bot_contact_point()
    commands = _RecordingContactPointCommands(contact_point)
    actor = _actor("parties.confirm_contact_point")
    async with AsyncClient(
        transport=ASGITransport(app=_app(actor, commands)), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/v1/parties/{contact_point.party_id}"
            f"/contact-points/{contact_point.contact_point_id}/confirm",
            headers={"Idempotency-Key": "confirm-contact"},
        )

    assert response.status_code == 200, response.text
    command = commands.confirm_commands[0]
    assert command.contact_point_id == contact_point.contact_point_id
    assert response.json()["contact_point_id"] == str(contact_point.contact_point_id)
