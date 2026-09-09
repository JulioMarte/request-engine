from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from request_engine.modules.tenancy.api.delegation_models import (
    CreateDelegationBody,
    DelegationRevisionView,
    DelegationView,
    RevokeDelegationBody,
)
from request_engine.modules.tenancy.api.party_registry_dependencies import IdempotencyKey
from request_engine.modules.tenancy.application.commands.delegation import (
    CreateDelegationCommand,
    DelegationCommands,
    RevokeDelegationCommand,
)
from request_engine.modules.tenancy.application.errors import (
    DelegationForbidden,
    DelegationInputInvalid,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext, PrincipalKind
from request_engine.platform.security.http import require_capability


def add_delegation_routes(
    router: APIRouter,
    *,
    commands: DelegationCommands,
    authenticated_actor: Callable[[Request], Awaitable[ActorContext]],
) -> None:
    def authorize(actor: ActorContext, capability: str, *, human_required: bool) -> None:
        require_capability(actor, capability)
        if human_required and actor.principal_kind is not PrincipalKind.HUMAN:
            raise DelegationForbidden("delegation creation requires a HUMAN actor")

    async def create_delegation(
        body: CreateDelegationBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> DelegationView:
        authorize(actor, "delegation.create", human_required=True)
        try:
            result = await commands.create_delegation(
                actor,
                CreateDelegationCommand(
                    delegate_principal_id=body.delegate_principal_id,
                    purpose=body.purpose,
                    allowed_capabilities=tuple(body.allowed_capabilities),
                    not_before=body.not_before,
                    expires_at=body.expires_at,
                    provenance_reference=body.provenance_reference,
                    idempotency_key=idempotency_key,
                ),
            )
        except ValueError as exc:
            raise DelegationInputInvalid(str(exc)) from None
        return DelegationView(delegation_id=result.delegation_id, revision=result.revision)

    async def revoke_delegation(
        delegation_id: UUID,
        body: RevokeDelegationBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> DelegationRevisionView:
        authorize(actor, "delegation.revoke", human_required=False)
        try:
            revision = await commands.revoke_delegation(
                actor,
                RevokeDelegationCommand(
                    delegation_id=delegation_id,
                    expected_revision=body.expected_revision,
                    provenance_reference=body.provenance_reference,
                    idempotency_key=idempotency_key,
                ),
            )
        except ValueError as exc:
            raise DelegationInputInvalid(str(exc)) from None
        return DelegationRevisionView(delegation_revision=revision)

    add_capability_route(
        router,
        "",
        create_delegation,
        capability="delegation.create",
        methods=["POST"],
        operation_id="delegation_create",
        response_model=DelegationView,
        status_code=status.HTTP_201_CREATED,
    )
    add_capability_route(
        router,
        "/{delegation_id}/revoke",
        revoke_delegation,
        capability="delegation.revoke",
        methods=["POST"],
        operation_id="delegation_revoke",
        response_model=DelegationRevisionView,
    )
