"""Operator-granted party correction routes (`parties.rename`, `parties.add_document`).

Transport route handlers map request values verbatim into application
commands: document normalization happens only in the application layer, and
these capabilities are grant-gated like every other party registry command.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from request_engine.modules.tenancy.api.party_registry_dependencies import (
    IdempotencyKey,
    source_kind,
)
from request_engine.modules.tenancy.api.party_registry_errors import PartyRegistryInputInvalid
from request_engine.modules.tenancy.api.party_registry_models import (
    AddPartyDocumentBody,
    PartyIdentityDocumentView,
    RegisteredPartyView,
    RenamePartyBody,
)
from request_engine.modules.tenancy.application.commands import (
    add_party_document,
    rename_party,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import require_capability

ActorDependency = Callable[[Request], Awaitable[ActorContext]]


def add_party_correction_routes(
    router: APIRouter,
    *,
    rename_handler: rename_party.RenamePartyHandler,
    add_document_handler: add_party_document.AddPartyDocumentHandler,
    authenticated_actor: ActorDependency,
) -> None:
    async def rename_route(
        party_id: UUID,
        body: RenamePartyBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> RegisteredPartyView:
        require_capability(actor, "parties.rename")
        try:
            party = await rename_party.rename_party(
                rename_handler,
                rename_party.RenamePartyCommand(
                    organization_id=actor.organization_id,
                    principal_id=actor.principal_id,
                    party_id=party_id,
                    display_name=body.display_name,
                    idempotency_key=idempotency_key,
                    source_kind=source_kind(actor),
                    platform=actor.platform,
                    technical_principal_id=actor.technical_principal_id,
                ),
            )
        except ValueError as error:
            raise PartyRegistryInputInvalid(str(error)) from None
        return RegisteredPartyView.from_contract(party)

    async def add_document_route(
        party_id: UUID,
        body: AddPartyDocumentBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> PartyIdentityDocumentView:
        require_capability(actor, "parties.add_document")
        try:
            document = await add_party_document.add_party_document(
                add_document_handler,
                add_party_document.AddPartyDocumentCommand(
                    organization_id=actor.organization_id,
                    principal_id=actor.principal_id,
                    party_id=party_id,
                    kind=body.kind,
                    value=body.value,
                    source_kind=source_kind(actor),
                    idempotency_key=idempotency_key,
                    platform=actor.platform,
                    technical_principal_id=actor.technical_principal_id,
                ),
            )
        except ValueError as error:
            raise PartyRegistryInputInvalid(str(error)) from None
        return PartyIdentityDocumentView.from_contract(document)

    add_capability_route(
        router,
        "/{party_id}/rename",
        rename_route,
        capability="parties.rename",
        methods=["POST"],
        response_model=RegisteredPartyView,
    )
    add_capability_route(
        router,
        "/{party_id}/documents",
        add_document_route,
        capability="parties.add_document",
        methods=["POST"],
        response_model=PartyIdentityDocumentView,
        status_code=status.HTTP_201_CREATED,
    )
