from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.tenancy.api.party_registry_dependencies import IdempotencyKey
from request_engine.modules.tenancy.application.commands.staff_representations import (
    ReplaceStaffRepresentationsCommand,
    StaffRepresentationCommands,
)
from request_engine.modules.tenancy.application.errors import (
    StaffMembershipForbidden,
    StaffMembershipInputInvalid,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext, PrincipalKind
from request_engine.platform.security.http import require_capability


class StaffRepresentationsReplaceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_authority_revision: int = Field(ge=1)
    desired_scopes: list[str] = Field(max_length=4)
    provenance_reference: str = Field(min_length=1, max_length=500)


class StaffRepresentationsReplaceView(BaseModel):
    membership_id: UUID
    authority_party_id: UUID
    authority_revision: int
    scopes: list[str]
    added: list[str]
    removed: list[str]


class StaffRepresentationView(BaseModel):
    representation_id: UUID
    authority_party_id: UUID
    scope_key: str
    authority_kind: str
    delegable: bool
    granted_by_principal_id: UUID | None
    valid_from: datetime
    valid_until: datetime | None
    revision: int


class StaffRepresentationsView(BaseModel):
    membership_id: UUID
    principal_id: UUID
    authority_revision: int
    representations: list[StaffRepresentationView]


def add_staff_representation_routes(
    router: APIRouter,
    *,
    commands: StaffRepresentationCommands,
    authenticated_actor: Callable[[Request], Awaitable[ActorContext]],
) -> None:
    def authorize(actor: ActorContext, capability: str) -> None:
        require_capability(actor, capability)
        if actor.principal_kind is not PrincipalKind.HUMAN:
            raise StaffMembershipForbidden("staff Representation operations require a HUMAN actor")

    async def read_representations(
        membership_id: UUID,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        response: Response,
    ) -> StaffRepresentationsView:
        authorize(actor, "staff.read")
        response.headers["Cache-Control"] = "no-store"
        state = await commands.read_staff_representations(actor, membership_id)
        return StaffRepresentationsView(
            membership_id=state.membership_id,
            principal_id=state.principal_id,
            authority_revision=state.authority_revision,
            representations=[
                StaffRepresentationView(
                    representation_id=item.representation_id,
                    authority_party_id=item.authority_party_id,
                    scope_key=item.scope_key,
                    authority_kind=item.authority_kind,
                    delegable=item.delegable,
                    granted_by_principal_id=item.granted_by_principal_id,
                    valid_from=item.valid_from,
                    valid_until=item.valid_until,
                    revision=item.revision,
                )
                for item in state.representations
            ],
        )

    async def replace_representations(
        membership_id: UUID,
        authority_party_id: UUID,
        body: StaffRepresentationsReplaceBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> StaffRepresentationsReplaceView:
        authorize(actor, "staff.manage_authority")
        try:
            result = await commands.replace_staff_representations(
                actor,
                ReplaceStaffRepresentationsCommand(
                    membership_id=membership_id,
                    authority_party_id=authority_party_id,
                    expected_authority_revision=body.expected_authority_revision,
                    desired_scopes=tuple(body.desired_scopes),
                    provenance_reference=body.provenance_reference,
                    idempotency_key=idempotency_key,
                ),
            )
        except ValueError as exc:
            raise StaffMembershipInputInvalid(str(exc)) from None
        return StaffRepresentationsReplaceView(
            membership_id=result.membership_id,
            authority_party_id=result.authority_party_id,
            authority_revision=result.authority_revision,
            scopes=list(result.scopes),
            added=list(result.added),
            removed=list(result.removed),
        )

    add_capability_route(
        router,
        "/members/{membership_id}/representations",
        read_representations,
        methods=["GET"],
        capability="staff.read",
        operation_id="staff_representations_list",
        response_model=StaffRepresentationsView,
    )
    add_capability_route(
        router,
        "/members/{membership_id}/representations/{authority_party_id}",
        replace_representations,
        methods=["PUT"],
        capability="staff.manage_authority",
        operation_id="staff_manage_representations",
        response_model=StaffRepresentationsReplaceView,
    )
