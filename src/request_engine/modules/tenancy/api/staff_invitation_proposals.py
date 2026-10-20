"""Staff invitation proposal transport: agents propose, HUMAN inviters decide (ADR 0019)."""

from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from request_engine.modules.tenancy.api.party_registry_dependencies import IdempotencyKey
from request_engine.modules.tenancy.api.staff_invitations import delivery_failure_response
from request_engine.modules.tenancy.application.commands.staff_invitation_proposals import (
    PROPOSAL_DISPLAY_NAME_MAX,
    PROPOSAL_NOTE_MAX,
    PROPOSAL_REJECTION_REASON_MAX,
    ApproveStaffInvitationProposalCommand,
    ProposeStaffInvitationCommand,
    RejectStaffInvitationProposalCommand,
    StaffInvitationProposal,
    StaffInvitationProposalStatus,
)
from request_engine.modules.tenancy.application.commands.staff_invitations import (
    normalize_invitation_email,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.http.errors import ErrorEnvelope
from request_engine.platform.secrets.delivery import RecoveryDeliveryError
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.freshness import require_recent_admin_authentication
from request_engine.platform.security.http import require_capability
from request_engine.platform.security.principal_authority import CapabilityRequired


class StaffInvitationProposalCommands(Protocol):
    async def propose(
        self, actor: ActorContext, command: ProposeStaffInvitationCommand
    ) -> StaffInvitationProposal: ...
    async def list(
        self,
        actor: ActorContext,
        *,
        status: StaffInvitationProposalStatus | None,
        after: UUID | None,
        limit: int,
    ) -> tuple[StaffInvitationProposal, ...]: ...
    async def get(self, actor: ActorContext, proposal_id: UUID) -> StaffInvitationProposal: ...
    async def approve(
        self, actor: ActorContext, command: ApproveStaffInvitationProposalCommand
    ) -> StaffInvitationProposal: ...
    async def reject(
        self, actor: ActorContext, command: RejectStaffInvitationProposalCommand
    ) -> StaffInvitationProposal: ...


class StaffInvitationProposalCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)
    display_name: str | None = Field(default=None, max_length=PROPOSAL_DISPLAY_NAME_MAX)
    note: str | None = Field(default=None, max_length=PROPOSAL_NOTE_MAX)
    provenance_reference: str = Field(min_length=1, max_length=500)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        return normalize_invitation_email(value)


class StaffInvitationProposalApproveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    expires_in_hours: int = Field(default=72, ge=1, le=168)
    provenance_reference: str = Field(min_length=1, max_length=500)


class StaffInvitationProposalRejectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=PROPOSAL_REJECTION_REASON_MAX)
    provenance_reference: str = Field(min_length=1, max_length=500)


class StaffInvitationProposalView(BaseModel):
    proposal_id: UUID
    organization_id: UUID
    email: str
    display_name: str | None
    note: str | None
    status: StaffInvitationProposalStatus
    revision: int
    proposed_by_principal_id: UUID
    proposed_by_principal_kind: str
    proposed_by_display_name: str | None
    created_at: datetime
    decided_at: datetime | None
    decided_by_principal_id: UUID | None
    invitation_id: UUID | None
    rejection_reason: str | None


class StaffInvitationProposalPageView(BaseModel):
    items: list[StaffInvitationProposalView]
    next_after: UUID | None


class StaffInvitationProposalParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: StaffInvitationProposalStatus | None = None
    after: UUID | None = None
    limit: int = Field(default=50, ge=1, le=100)


def _view(proposal: StaffInvitationProposal) -> StaffInvitationProposalView:
    return StaffInvitationProposalView.model_validate(asdict(proposal))


def create_staff_invitation_proposal_router(
    *,
    commands: StaffInvitationProposalCommands,
    authenticated_actor: Callable[[Request], Awaitable[ActorContext]],
) -> APIRouter:
    router = APIRouter(prefix="/v1/staff/invitation-proposals", tags=["staff invitation proposals"])

    async def create(
        body: StaffInvitationProposalCreateBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
        response: Response,
    ) -> StaffInvitationProposalView:
        require_capability(actor, "staff.propose_invitation")
        response.headers["Cache-Control"] = "no-store"
        return _view(
            await commands.propose(
                actor,
                ProposeStaffInvitationCommand(
                    email=body.email,
                    display_name=body.display_name,
                    note=body.note,
                    provenance_reference=body.provenance_reference,
                    idempotency_key=idempotency_key,
                ),
            )
        )

    async def list_proposals(
        params: Annotated[StaffInvitationProposalParams, Query()],
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        response: Response,
    ) -> StaffInvitationProposalPageView:
        require_capability(actor, "staff.read")
        rows = await commands.list(
            actor, status=params.status, after=params.after, limit=params.limit + 1
        )
        page = rows[: params.limit]
        response.headers["Cache-Control"] = "no-store"
        return StaffInvitationProposalPageView(
            items=[_view(row) for row in page],
            next_after=page[-1].proposal_id if len(rows) > params.limit else None,
        )

    async def get(
        proposal_id: UUID,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        response: Response,
    ) -> StaffInvitationProposalView:
        # Administrators read any tenant proposal; a proposer reads only its own.
        if not (actor.allows("staff.read") or actor.allows("staff.propose_invitation")):
            raise CapabilityRequired("staff.read")
        response.headers["Cache-Control"] = "no-store"
        return _view(await commands.get(actor, proposal_id))

    async def approve(
        proposal_id: UUID,
        body: StaffInvitationProposalApproveBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
        response: Response,
    ) -> StaffInvitationProposalView | JSONResponse:
        require_capability(actor, "staff.invite")
        require_recent_admin_authentication(actor, now=datetime.now(UTC))
        response.headers["Cache-Control"] = "no-store"
        try:
            result = await commands.approve(
                actor,
                ApproveStaffInvitationProposalCommand(
                    proposal_id=proposal_id,
                    expected_revision=body.expected_revision,
                    expires_in_hours=body.expires_in_hours,
                    provenance_reference=body.provenance_reference,
                    idempotency_key=idempotency_key,
                ),
            )
        except RecoveryDeliveryError as exc:
            return delivery_failure_response(exc, allow_same_request_retry=True)
        return _view(result)

    async def reject(
        proposal_id: UUID,
        body: StaffInvitationProposalRejectBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
        response: Response,
    ) -> StaffInvitationProposalView:
        require_capability(actor, "staff.invite")
        require_recent_admin_authentication(actor, now=datetime.now(UTC))
        response.headers["Cache-Control"] = "no-store"
        return _view(
            await commands.reject(
                actor,
                RejectStaffInvitationProposalCommand(
                    proposal_id=proposal_id,
                    expected_revision=body.expected_revision,
                    reason=body.reason,
                    provenance_reference=body.provenance_reference,
                    idempotency_key=idempotency_key,
                ),
            )
        )

    read_errors = {code: {"model": ErrorEnvelope} for code in (401, 403, 404, 422)}
    command_errors = {**read_errors, 409: {"model": ErrorEnvelope}}
    add_capability_route(
        router,
        "",
        create,
        capability="staff.propose_invitation",
        methods=["POST"],
        operation_id="staff_invitation_proposal_create",
        tool_name="staff_invitation_propose",
        tool_audiences=("operator",),
        response_model=StaffInvitationProposalView,
        status_code=201,
        summary="Propose adding a person to the business as staff",
        description="Records a pending proposal for a HUMAN staff administrator to approve "
        "or reject. Creates no invitation, membership or permission and sends no email. "
        "Requires Idempotency-Key; a second pending proposal for the same email returns 409.",
        responses=command_errors,
    )
    add_capability_route(
        router,
        "",
        list_proposals,
        capability="staff.read",
        methods=["GET"],
        operation_id="staff_invitation_proposal_list",
        response_model=StaffInvitationProposalPageView,
        summary="List staff invitation proposals (approvals inbox)",
        description="Use status=pending for the approvals inbox. Keyset pagination by id.",
        responses=read_errors,
    )
    add_capability_route(
        router,
        "/{proposal_id}",
        get,
        capability="staff.read",
        methods=["GET"],
        operation_id="staff_invitation_proposal_get",
        response_model=StaffInvitationProposalView,
        summary="Read one staff invitation proposal",
        description="HUMAN staff.read sees any tenant proposal. A caller holding only "
        "staff.propose_invitation sees only proposals it created; others return 404.",
        responses=read_errors,
    )
    add_capability_route(
        router,
        "/{proposal_id}:approve",
        approve,
        capability="staff.invite",
        methods=["POST"],
        operation_id="staff_invitation_proposal_approve",
        response_model=StaffInvitationProposalView,
        summary="Approve a proposal and create the staff invitation",
        description="HUMAN only, recent authentication, expected_revision and Idempotency-Key. "
        "Creates the invitation through the same path as staff_invitation_create in one "
        "transaction. Temporary staging 503: retry the same request and key.",
        responses={**command_errors, 503: {"model": ErrorEnvelope}},
    )
    add_capability_route(
        router,
        "/{proposal_id}:reject",
        reject,
        capability="staff.invite",
        methods=["POST"],
        operation_id="staff_invitation_proposal_reject",
        response_model=StaffInvitationProposalView,
        summary="Reject a staff invitation proposal",
        description="HUMAN only, recent authentication, expected_revision and Idempotency-Key.",
        responses=command_errors,
    )
    return router
