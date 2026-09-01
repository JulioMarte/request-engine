"""Correction HTTP error mapping: fail-closed 404s and enriched 409 conflicts."""

from uuid import uuid4

import pytest
from fastapi import APIRouter, FastAPI, Request
from httpx import ASGITransport, AsyncClient

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
from request_engine.modules.tenancy.application.errors import (
    PartyDocumentConflict,
    PartyNotFound,
)
from request_engine.modules.tenancy.contracts.party_registry import (
    PartyContactPoint,
    PartyIdentityDocument,
    RegisteredParty,
)
from request_engine.platform.security.context import ActorContext

_GRANTS = frozenset(
    {
        "parties.rename",
        "parties.add_document",
        "parties.deactivate_contact_point",
        "parties.deactivate",
    }
)


class _FailingCorrections:
    def __init__(self, error: Exception) -> None:
        self._error = error

    async def rename_party(self, command: rename_party.RenamePartyCommand) -> RegisteredParty:
        raise self._error

    async def add_party_document(
        self, command: add_party_document.AddPartyDocumentCommand
    ) -> PartyIdentityDocument:
        raise self._error

    async def deactivate_party_contact_point(
        self, command: deactivate_party_contact_point.DeactivatePartyContactPointCommand
    ) -> PartyContactPoint:
        raise self._error

    async def deactivate_party(
        self, command: deactivate_party.DeactivatePartyCommand
    ) -> RegisteredParty:
        raise self._error


async def _granted_actor(request: Request) -> ActorContext:
    del request
    return ActorContext(organization_id=uuid4(), principal_id=uuid4(), capabilities=_GRANTS)


def _app(error: Exception) -> FastAPI:
    failing = _FailingCorrections(error)
    router = APIRouter(prefix="/v1/parties")
    add_party_correction_routes(
        router,
        rename_handler=failing,
        add_document_handler=failing,
        authenticated_actor=_granted_actor,
    )
    add_party_deactivation_routes(
        router,
        deactivate_contact_point_handler=failing,
        deactivate_party_handler=failing,
        authenticated_actor=_granted_actor,
    )
    app = FastAPI()
    app.include_router(router)
    add_party_registry_error_handlers(app)
    return app


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "body"),
    (
        ("/v1/parties/00000000-0000-4000-8000-000000000001/rename", {"display_name": "X"}),
        (
            "/v1/parties/00000000-0000-4000-8000-000000000001/documents",
            {"kind": "cedula", "value": "40212345678"},
        ),
        ("/v1/parties/00000000-0000-4000-8000-000000000001/deactivate", None),
    ),
)
async def test_fail_closed_targets_map_to_typed_party_not_found(
    path: str, body: dict[str, str] | None
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=_app(PartyNotFound(uuid4()))), base_url="http://test"
    ) as client:
        response = await client.post(path, json=body, headers={"Idempotency-Key": "nf-1"})

    assert response.status_code == 404, response.text
    error = response.json()["error"]
    assert error["code"] == "party_not_found"
    assert error["resolution"] == "fix_request"


@pytest.mark.asyncio
async def test_add_document_conflict_names_the_holding_party() -> None:
    holder_id = uuid4()
    error = PartyDocumentConflict(
        "identity document value already registered for another party",
        existing_party_id=holder_id,
        existing_display_name="Alma Bien",
    )
    async with AsyncClient(
        transport=ASGITransport(app=_app(error)), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/parties/00000000-0000-4000-8000-000000000001/documents",
            json={"kind": "cedula", "value": "40212345678"},
            headers={"Idempotency-Key": "conflict-1"},
        )

    assert response.status_code == 409, response.text
    details = response.json()["error"]["details"]
    assert details["existing_party_id"] == str(holder_id)
    assert details["existing_display_name"] == "Alma Bien"
