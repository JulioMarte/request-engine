"""Staff administrative contact routes (docs/v3/38 §9.2).

`principal_id` is forced from the authenticated actor; a non-human caller
gets the typed 403. No response ever carries the one-time code.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from request_engine.modules.tenancy.api.party_registry_dependencies import IdempotencyKey
from request_engine.modules.tenancy.api.party_registry_errors import PartyRegistryInputInvalid
from request_engine.modules.tenancy.api.staff_contact_models import (
    StaffContactBody,
    StaffContactConfirmBody,
    StaffContactVerificationIssuedView,
    StaffContactView,
)
from request_engine.modules.tenancy.application.commands import (
    confirm_principal_contact,
    register_principal_contact,
)
from request_engine.modules.tenancy.application.commands import (
    request_principal_contact_verification as request_cmd,
)
from request_engine.modules.tenancy.application.errors import StaffContactForbidden
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext, PrincipalKind
from request_engine.platform.security.http import require_capability


def add_staff_contact_routes(
    router: APIRouter,
    *,
    register_handler: register_principal_contact.RegisterPrincipalContactHandler,
    verification_handler: request_cmd.RequestPrincipalContactVerificationHandler,
    confirm_handler: confirm_principal_contact.ConfirmPrincipalContactHandler,
    authenticated_actor: Callable[[Request], Awaitable[ActorContext]],
) -> None:
    def _authorize(actor: ActorContext, capability: str) -> None:
        require_capability(actor, capability)
        if actor.principal_kind is not PrincipalKind.HUMAN:
            raise StaffContactForbidden(actor.principal_id)

    async def register_route(
        body: StaffContactBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> StaffContactView:
        _authorize(actor, "staff.manage_own_admin_contact")
        try:
            contact = await register_principal_contact.register_principal_contact(
                register_handler,
                register_principal_contact.RegisterPrincipalContactCommand(
                    actor.organization_id,
                    actor.principal_id,
                    body.channel,
                    body.value,
                    idempotency_key,
                ),
            )
        except ValueError as error:
            raise PartyRegistryInputInvalid(str(error)) from None
        return StaffContactView.from_contract(contact)

    async def request_verification_route(
        contact_id: UUID,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> StaffContactVerificationIssuedView:
        _authorize(actor, "staff.manage_own_admin_contact")
        command = request_cmd.RequestPrincipalContactVerificationCommand(
            actor.organization_id, actor.principal_id, contact_id, idempotency_key
        )
        issued = await request_cmd.request_principal_contact_verification(
            verification_handler, command
        )
        return StaffContactVerificationIssuedView.from_contract(issued)

    async def confirm_route(
        contact_id: UUID,
        body: StaffContactConfirmBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> StaffContactView:
        _authorize(actor, "staff.confirm_own_admin_contact")
        try:
            contact = await confirm_principal_contact.confirm_principal_contact(
                confirm_handler,
                confirm_principal_contact.ConfirmPrincipalContactCommand(
                    actor.organization_id,
                    actor.principal_id,
                    contact_id,
                    body.code,
                    idempotency_key,
                ),
            )
        except ValueError as error:
            raise PartyRegistryInputInvalid(str(error)) from None
        return StaffContactView.from_contract(contact)

    add_capability_route(
        router,
        "/contacts",
        register_route,
        capability="staff.manage_own_admin_contact",
        methods=["POST"],
        operation_id="staff_manage_own_admin_contact_register",
        response_model=StaffContactView,
        status_code=status.HTTP_201_CREATED,
    )
    add_capability_route(
        router,
        "/contacts/{contact_id}/request-verification",
        request_verification_route,
        capability="staff.manage_own_admin_contact",
        methods=["POST"],
        operation_id="staff_manage_own_admin_contact_request_verification",
        response_model=StaffContactVerificationIssuedView,
    )
    add_capability_route(
        router,
        "/contacts/{contact_id}/confirm",
        confirm_route,
        capability="staff.confirm_own_admin_contact",
        methods=["POST"],
        response_model=StaffContactView,
    )
