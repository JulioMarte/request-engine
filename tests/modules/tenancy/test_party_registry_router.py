from typing import Any
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
from request_engine.modules.tenancy.application.commands import register_party
from request_engine.modules.tenancy.contracts.party_registry import (
    PartyContactPointInput,
    PartyDocumentInput,
    RegisteredParty,
    RegisteredVia,
)
from request_engine.platform.security.context import ActorContext, PrincipalKind
from request_engine.platform.security.http import CapabilityRequired


class _FixedActorResolver:
    def __init__(self, actor: ActorContext) -> None:
        self._actor = actor

    async def resolve_actor(self, request: Request) -> ActorContext:
        del request
        return self._actor


class _RecordingRegistration:
    def __init__(self, party: RegisteredParty) -> None:
        self.commands: list[register_party.RegisterPartyCommand] = []
        self._party = party

    async def register_party(self, command: register_party.RegisterPartyCommand) -> RegisteredParty:
        self.commands.append(command)
        return self._party


def _registered_party() -> RegisteredParty:
    party_id = uuid4()
    return RegisteredParty(
        party_id=party_id,
        organization_id=uuid4(),
        party_kind="person",
        display_name="Jose Perez",
        active=True,
        contact_points=(),
        documents=(),
    )


def _actor(*capabilities: str, principal_kind: PrincipalKind = PrincipalKind.HUMAN) -> ActorContext:
    return ActorContext(
        organization_id=uuid4(),
        principal_id=uuid4(),
        capabilities=frozenset(capabilities),
        principal_kind=principal_kind,
    )


def _app(actor: ActorContext, registration: _RecordingRegistration) -> FastAPI:
    unused: Any = object()
    router = APIRouter(prefix="/v1/parties")
    add_party_registry_routes(
        router,
        register_handler=registration,
        add_contact_point_handler=unused,
        confirm_handler=unused,
        lookup_reader=unused,
        actor_resolver=_FixedActorResolver(actor),
    )
    app = FastAPI()
    app.include_router(router)
    add_party_registry_error_handlers(app)
    app.add_exception_handler(CapabilityRequired, capability_required_handler)
    app.add_exception_handler(RequestValidationError, request_validation_error_handler)
    return app


@pytest.mark.asyncio
async def test_register_maps_body_to_command_and_derives_attribution_server_side() -> None:
    """Transport values pass verbatim; attribution derives from the principal kind."""

    registration = _RecordingRegistration(_registered_party())
    actor = _actor("parties.register", principal_kind=PrincipalKind.INTEGRATION)
    async with AsyncClient(
        transport=ASGITransport(app=_app(actor, registration)), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/parties",
            json={
                "display_name": "Jose Perez",
                "contact_points": [{"channel": "phone", "value": "(809) 555-1234"}],
                "documents": [{"kind": "cedula", "value": "402-1234567-8"}],
            },
            headers={"Idempotency-Key": "register-attribution"},
        )

    assert response.status_code == 201, response.text
    command = registration.commands[0]
    assert command.registered_via is RegisteredVia.BOT
    assert command.contact_points == (PartyContactPointInput("phone", "+18095551234"),)
    assert command.documents == (PartyDocumentInput("cedula", "40212345678"),)


@pytest.mark.asyncio
async def test_register_rejects_actor_without_capability_before_reaching_the_command() -> None:
    registration = _RecordingRegistration(_registered_party())
    async with AsyncClient(
        transport=ASGITransport(app=_app(_actor(), registration)), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/parties",
            json={"display_name": "Jose Perez"},
            headers={"Idempotency-Key": "register-forbidden"},
        )

    assert response.status_code == 403, response.text
    error = response.json()["error"]
    assert error["code"] == "capability_required"
    assert error["details"] == {"capability": "parties.register"}
    assert registration.commands == []
