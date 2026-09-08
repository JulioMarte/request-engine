from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field

from request_engine.modules.tenancy.api.party_registry_dependencies import IdempotencyKey
from request_engine.modules.tenancy.application.commands.staff_membership import (
    InviteNativeStaffCommand,
    ReplaceStaffAuthorityCommand,
    StaffMembershipCommands,
    StaffMembershipTargetStatus,
    TransitionStaffMembershipCommand,
)
from request_engine.modules.tenancy.application.errors import (
    StaffMembershipForbidden,
    StaffMembershipInputInvalid,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext, PrincipalKind
from request_engine.platform.security.http import require_capability


class NativeStaffInviteBody(BaseModel):
    identity_authority_id: UUID
    native_identity_id: UUID
    provenance_reference: str = Field(min_length=1, max_length=500)


class NativeStaffInviteView(BaseModel):
    membership_id: UUID
    principal_id: UUID
    binding_id: UUID
    status: str = "invited"


class StaffAuthorityReplaceBody(BaseModel):
    expected_authority_revision: int = Field(ge=1)
    desired_capabilities: list[str] = Field(max_length=128)
    provenance_reference: str = Field(min_length=1, max_length=500)


class StaffAuthorityReplaceView(BaseModel):
    authority_revision: int


class StaffMembershipTransitionBody(BaseModel):
    expected_revision: int = Field(ge=1)
    target_status: StaffMembershipTargetStatus
    provenance_reference: str = Field(min_length=1, max_length=500)


class StaffMembershipTransitionView(BaseModel):
    membership_revision: int


def add_staff_membership_routes(
    router: APIRouter,
    *,
    commands: StaffMembershipCommands,
    authenticated_actor: Callable[[Request], Awaitable[ActorContext]],
) -> None:
    def authorize(actor: ActorContext, capability: str) -> None:
        require_capability(actor, capability)
        if actor.principal_kind is not PrincipalKind.HUMAN:
            raise StaffMembershipForbidden("staff lifecycle commands require a HUMAN actor")

    async def invite_native_staff(
        body: NativeStaffInviteBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> NativeStaffInviteView:
        authorize(actor, "staff.invite")
        try:
            result = await commands.invite_native_staff(
                actor,
                InviteNativeStaffCommand(
                    identity_authority_id=body.identity_authority_id,
                    native_identity_id=body.native_identity_id,
                    provenance_reference=body.provenance_reference,
                    idempotency_key=idempotency_key,
                ),
            )
        except ValueError as exc:
            raise StaffMembershipInputInvalid(str(exc)) from None
        return NativeStaffInviteView(
            membership_id=result.membership_id,
            principal_id=result.principal_id,
            binding_id=result.binding_id,
        )

    async def replace_authority(
        membership_id: UUID,
        body: StaffAuthorityReplaceBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> StaffAuthorityReplaceView:
        authorize(actor, "staff.manage_authority")
        try:
            revision = await commands.replace_staff_authority(
                actor,
                ReplaceStaffAuthorityCommand(
                    membership_id=membership_id,
                    expected_authority_revision=body.expected_authority_revision,
                    desired_capabilities=tuple(body.desired_capabilities),
                    provenance_reference=body.provenance_reference,
                    idempotency_key=idempotency_key,
                ),
            )
        except ValueError as exc:
            raise StaffMembershipInputInvalid(str(exc)) from None
        return StaffAuthorityReplaceView(authority_revision=revision)

    async def transition_membership(
        membership_id: UUID,
        body: StaffMembershipTransitionBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> StaffMembershipTransitionView:
        authorize(actor, "staff.manage_membership")
        try:
            revision = await commands.transition_staff_membership(
                actor,
                TransitionStaffMembershipCommand(
                    membership_id=membership_id,
                    expected_revision=body.expected_revision,
                    target_status=body.target_status,
                    provenance_reference=body.provenance_reference,
                    idempotency_key=idempotency_key,
                ),
            )
        except ValueError as exc:
            raise StaffMembershipInputInvalid(str(exc)) from None
        return StaffMembershipTransitionView(membership_revision=revision)

    add_capability_route(
        router,
        "/members/native",
        invite_native_staff,
        capability="staff.invite",
        methods=["POST"],
        operation_id="staff_invite",
        response_model=NativeStaffInviteView,
        status_code=status.HTTP_201_CREATED,
    )
    add_capability_route(
        router,
        "/members/{membership_id}/authority",
        replace_authority,
        capability="staff.manage_authority",
        methods=["PUT"],
        operation_id="staff_manage_authority",
        response_model=StaffAuthorityReplaceView,
    )
    add_capability_route(
        router,
        "/members/{membership_id}/status",
        transition_membership,
        capability="staff.manage_membership",
        methods=["PUT"],
        operation_id="staff_manage_membership",
        response_model=StaffMembershipTransitionView,
    )
