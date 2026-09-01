"""The correction capabilities are grant-gated: an INTEGRATION-kind actor
(bot principal) without the grants is rejected before any command runs, so
bots can create and look up parties but never correct or deactivate them."""

from uuid import uuid4

import pytest
from fastapi import APIRouter, FastAPI, Request
from httpx import ASGITransport, AsyncClient

from request_engine.entrypoints.http.errors import capability_required_handler
from request_engine.modules.tenancy.api.party_registry_correction_routes import (
    add_party_correction_routes,
)
from request_engine.modules.tenancy.api.party_registry_deactivation_routes import (
    add_party_deactivation_routes,
)
from request_engine.modules.tenancy.api.party_registry_errors import (
    add_party_registry_error_handlers,
)
from request_engine.modules.tenancy.application.commands import (
    add_party_document,
    deactivate_party,
    deactivate_party_contact_point,
    rename_party,
)
from request_engine.modules.tenancy.contracts.party_registry import (
    PartyContactPoint,
    PartyIdentityDocument,
    RegisteredParty,
)
from request_engine.platform.security.context import ActorContext, PrincipalKind
from request_engine.platform.security.http import CapabilityRequired


class _UnreachableCorrections:
    """Every correction handler must be unreachable without the capability."""

    async def rename_party(self, command: rename_party.RenamePartyCommand) -> RegisteredParty:
        raise AssertionError("parties.rename must never run for an ungranted bot")

    async def add_party_document(
        self, command: add_party_document.AddPartyDocumentCommand
    ) -> PartyIdentityDocument:
        raise AssertionError("parties.add_document must never run for an ungranted bot")

    async def deactivate_party_contact_point(
        self, command: deactivate_party_contact_point.DeactivatePartyContactPointCommand
    ) -> PartyContactPoint:
        raise AssertionError("parties.deactivate_contact_point must never run for an ungranted bot")

    async def deactivate_party(
        self, command: deactivate_party.DeactivatePartyCommand
    ) -> RegisteredParty:
        raise AssertionError("parties.deactivate must never run for an ungranted bot")


def _bot_app() -> FastAPI:
    commands = _UnreachableCorrections()
    actor = ActorContext(
        organization_id=uuid4(),
        principal_id=uuid4(),
        capabilities=frozenset(),
        principal_kind=PrincipalKind.INTEGRATION,
    )

    async def actor_dependency(request: Request) -> ActorContext:
        del request
        return actor

    router = APIRouter(prefix="/v1/parties")
    add_party_correction_routes(
        router,
        rename_handler=commands,
        add_document_handler=commands,
        authenticated_actor=actor_dependency,
    )
    add_party_deactivation_routes(
        router,
        deactivate_contact_point_handler=commands,
        deactivate_party_handler=commands,
        authenticated_actor=actor_dependency,
    )
    app = FastAPI()
    app.include_router(router)
    add_party_registry_error_handlers(app)
    app.add_exception_handler(CapabilityRequired, capability_required_handler)
    return app


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("capability", "path", "body"),
    (
        (
            "parties.rename",
            "/v1/parties/00000000-0000-4000-8000-000000000001/rename",
            {"display_name": "X"},
        ),
        (
            "parties.add_document",
            "/v1/parties/00000000-0000-4000-8000-000000000001/documents",
            {"kind": "cedula", "value": "40212345678"},
        ),
        (
            "parties.deactivate_contact_point",
            "/v1/parties/00000000-0000-4000-8000-000000000001/contact-points/00000000-0000-4000-8000-000000000002/deactivate",
            None,
        ),
        ("parties.deactivate", "/v1/parties/00000000-0000-4000-8000-000000000001/deactivate", None),
    ),
)
async def test_bot_principal_without_grants_is_rejected_before_any_command(
    capability: str, path: str, body: dict[str, str] | None
) -> None:
    app = _bot_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(path, json=body, headers={"Idempotency-Key": "bot-1"})

    assert response.status_code == 403, response.text
    error = response.json()["error"]
    assert error["code"] == "capability_required"
    assert error["details"] == {"capability": capability}
