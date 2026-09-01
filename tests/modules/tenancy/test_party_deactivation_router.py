"""Deactivation route command mapping: path identifiers map verbatim into the
application commands and the responses show the post-command views."""

from uuid import uuid4

import pytest
from fastapi import APIRouter, FastAPI, Request
from httpx import ASGITransport, AsyncClient

from request_engine.modules.tenancy.api.party_registry_deactivation_routes import (
    add_party_deactivation_routes,
)
from request_engine.modules.tenancy.api.party_registry_errors import (
    add_party_registry_error_handlers,
)
from request_engine.modules.tenancy.application.commands import (
    deactivate_party,
    deactivate_party_contact_point,
)
from request_engine.modules.tenancy.contracts.party_registry import (
    PartyContactPoint,
    RegisteredParty,
    RegisteredVia,
)
from request_engine.platform.security.context import ActorContext


class _FixedActorResolver:
    def __init__(self, actor: ActorContext) -> None:
        self._actor = actor

    async def resolve_actor(self, request: Request) -> ActorContext:
        del request
        return self._actor


class _RecordingDeactivations:
    def __init__(self) -> None:
        self.contact_points: list[
            deactivate_party_contact_point.DeactivatePartyContactPointCommand
        ] = []
        self.deactivations: list[deactivate_party.DeactivatePartyCommand] = []

    async def deactivate_party_contact_point(
        self, command: deactivate_party_contact_point.DeactivatePartyContactPointCommand
    ) -> PartyContactPoint:
        self.contact_points.append(command)
        return PartyContactPoint(
            command.party_id,
            command.contact_point_id,
            "whatsapp",
            "+18095551234",
            True,
            RegisteredVia.OPERATOR,
        )

    async def deactivate_party(
        self, command: deactivate_party.DeactivatePartyCommand
    ) -> RegisteredParty:
        self.deactivations.append(command)
        return RegisteredParty(
            party_id=command.party_id,
            organization_id=uuid4(),
            party_kind="person",
            display_name="Jose Perez",
            active=False,
            contact_points=(),
            documents=(),
        )


def _actor(*capabilities: str) -> ActorContext:
    return ActorContext(
        organization_id=uuid4(), principal_id=uuid4(), capabilities=frozenset(capabilities)
    )


def _app(actor: ActorContext, commands: _RecordingDeactivations) -> FastAPI:
    resolver = _FixedActorResolver(actor)
    router = APIRouter(prefix="/v1/parties")
    add_party_deactivation_routes(
        router,
        deactivate_contact_point_handler=commands,
        deactivate_party_handler=commands,
        authenticated_actor=resolver.resolve_actor,
    )
    app = FastAPI()
    app.include_router(router)
    add_party_registry_error_handlers(app)
    return app


async def _post(app: FastAPI, path: str, key: str):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(path, headers={"Idempotency-Key": key})


@pytest.mark.asyncio
async def test_deactivate_routes_map_path_identifiers_into_commands() -> None:
    party_id, contact_point_id = uuid4(), uuid4()
    commands = _RecordingDeactivations()
    app = _app(_actor("parties.deactivate_contact_point", "parties.deactivate"), commands)
    point = await _post(
        app, f"/v1/parties/{party_id}/contact-points/{contact_point_id}/deactivate", "cp-1"
    )
    deactivated = await _post(app, f"/v1/parties/{party_id}/deactivate", "party-1")

    assert point.status_code == 200, point.text
    assert deactivated.status_code == 200, deactivated.text
    assert commands.contact_points[0].contact_point_id == contact_point_id
    assert commands.deactivations[0].party_id == party_id
    assert deactivated.json()["active"] is False
