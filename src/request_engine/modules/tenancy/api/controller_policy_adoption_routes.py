from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request, Response
from fastapi import status as http_status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.tenancy.application.commands.controller_policy_adoption import (
    ApplyControllerPolicyAdoption,
    ControllerPolicyAdoptionCommands,
    ControllerPolicyAdoptionConflict,
    ControllerPolicyAdoptionConsentInvalidated,
    ControllerPolicyAdoptionDetail,
    ControllerPolicyAdoptionError,
    ControllerPolicyAdoptionForbidden,
    ControllerPolicyAdoptionInvalid,
    ControllerPolicyAdoptionNotFound,
    ControllerPolicyAdoptionReader,
    ControllerPolicyAdoptionReview,
    ControllerPolicyAdoptionSummary,
    ListControllerPolicyAdoptions,
    RequestControllerPolicyAdoption,
    WithdrawControllerPolicyAdoption,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope, ErrorResolution
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import require_capability
from request_engine.platform.security.platform_context import PlatformActorContext
from request_engine.platform.security.platform_http import require_platform_capability

ROOT_ADMISSION = "organization.bootstrap"
PLATFORM_ADOPTION = "platform.organization.adopt_initial_controller_policy"
PLATFORM_READ = "platform.organization.read"


def _adoption_idempotency_key(
    value: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=250)],
) -> str:
    """Normalize this command family's key and reject whitespace-only values as 422."""
    normalized = value.strip()
    if not normalized:
        raise ControllerPolicyAdoptionInvalid()
    return normalized


AdoptionIdempotencyKey = Annotated[str, Depends(_adoption_idempotency_key)]


class ControllerPolicyAdoptionRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_authority_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)


class ControllerPolicyAdoptionWithdrawBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_request_revision: int = Field(ge=1)


class ControllerPolicyAdoptionApplyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_request_revision: int = Field(ge=1)


class ControllerPolicyAdoptionRequestView(BaseModel):
    request_id: UUID
    source_policy_key: str
    target_policy_key: str
    authority_revision: int
    request_revision: int
    status: str
    expires_at: str


class ControllerPolicyAdoptionDetailView(BaseModel):
    request_id: UUID
    source_policy_key: str
    target_policy_key: str
    expected_authority_revision: int
    status: str
    request_revision: int
    created_at: datetime
    expires_at: datetime
    authority_revision_before: int | None
    authority_revision_after: int | None
    added_capabilities: tuple[str, ...]


class ControllerPolicyAdoptionWithdrawView(BaseModel):
    request_revision: int
    status: str


class ControllerPolicyAdoptionAppliedView(BaseModel):
    fact_id: UUID
    request_id: UUID
    organization_id: UUID
    controller_principal_id: UUID
    platform_approver_principal_id: UUID
    source_policy_key: str
    target_policy_key: str
    authority_revision_before: int
    authority_revision_after: int
    added_capabilities: tuple[str, ...]
    request_revision: int


class ControllerPolicyAdoptionSummaryView(BaseModel):
    request_id: UUID
    organization_id: UUID
    controller_principal_id: UUID
    source_policy_key: str
    target_policy_key: str
    expected_authority_revision: int
    status: str
    request_revision: int
    created_at: datetime
    expires_at: datetime


class ControllerPolicyAdoptionPageView(BaseModel):
    items: list[ControllerPolicyAdoptionSummaryView]
    next_after: UUID | None


class ControllerPolicyAdoptionReviewView(BaseModel):
    request_id: UUID
    organization_id: UUID
    controller_principal_id: UUID
    source_policy_key: str
    target_policy_key: str
    expected_authority_revision: int
    current_authority_revision: int
    request_revision: int
    reason: str
    expires_at: datetime
    proposed_capabilities: tuple[str, ...]
    revoked_capabilities: tuple[str, ...]
    proposed_delta_does_not_restore_revoked_capabilities: bool = Field(
        description=(
            "True only when the proposed capability delta contains no capabilities with "
            "revoked grant history. This is not apply eligibility: apply independently "
            "revalidates both native identities, recovery posture, consent, authority, "
            "and revisions."
        )
    )


def add_controller_policy_adoption_tenant_routes(
    router: APIRouter,
    *,
    commands: ControllerPolicyAdoptionCommands,
    authenticated_actor: Callable[[Request], Awaitable[ActorContext]],
) -> None:
    async def request_adoption(
        body: ControllerPolicyAdoptionRequestBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: AdoptionIdempotencyKey,
        response: Response,
    ) -> ControllerPolicyAdoptionRequestView:
        # This historical capability is an admission requirement. The owner
        # command independently requires the exact immutable root relationship,
        # active native binding, HUMAN kind and fresh phishing-resistant proof.
        require_capability(actor, ROOT_ADMISSION)
        result = await commands.request_adoption(
            actor,
            RequestControllerPolicyAdoption(
                expected_authority_revision=body.expected_authority_revision,
                reason=body.reason,
                idempotency_key=idempotency_key,
            ),
        )
        response.headers["Cache-Control"] = "no-store"
        return ControllerPolicyAdoptionRequestView(
            request_id=result.request_id,
            source_policy_key=result.source_policy_key,
            target_policy_key=result.target_policy_key,
            authority_revision=result.authority_revision,
            request_revision=result.request_revision,
            status=result.status,
            expires_at=result.expires_at,
        )

    async def withdraw_adoption(
        request_id: UUID,
        body: ControllerPolicyAdoptionWithdrawBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: AdoptionIdempotencyKey,
        response: Response,
    ) -> ControllerPolicyAdoptionWithdrawView:
        require_capability(actor, ROOT_ADMISSION)
        revision, state = await commands.withdraw_adoption(
            actor,
            WithdrawControllerPolicyAdoption(
                request_id=request_id,
                expected_request_revision=body.expected_request_revision,
                idempotency_key=idempotency_key,
            ),
        )
        response.headers["Cache-Control"] = "no-store"
        return ControllerPolicyAdoptionWithdrawView(request_revision=revision, status=state)

    async def get_adoption(
        request_id: UUID,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        response: Response,
    ) -> ControllerPolicyAdoptionDetailView:
        require_capability(actor, ROOT_ADMISSION)
        result = await commands.get_adoption(actor, request_id)
        response.headers["Cache-Control"] = "no-store"
        return _detail_view(result)

    add_capability_route(
        router,
        "/v1/controller-policy-adoptions/{request_id}",
        get_adoption,
        methods=["GET"],
        capability=ROOT_ADMISSION,
        operation_id="controller_policy_adoption_request_get",
        owner="tenancy",
        response_model=ControllerPolicyAdoptionDetailView,
        responses={status: {"model": ErrorEnvelope} for status in (401, 403, 404)},
    )
    add_capability_route(
        router,
        "/v1/controller-policy-adoptions",
        request_adoption,
        methods=["POST"],
        capability=ROOT_ADMISSION,
        operation_id="controller_policy_adoption_request_create",
        owner="tenancy",
        status_code=http_status.HTTP_201_CREATED,
        response_model=ControllerPolicyAdoptionRequestView,
        responses={status: {"model": ErrorEnvelope} for status in (401, 403, 409, 422)},
    )
    add_capability_route(
        router,
        "/v1/controller-policy-adoptions/{request_id}:withdraw",
        withdraw_adoption,
        methods=["POST"],
        capability=ROOT_ADMISSION,
        operation_id="controller_policy_adoption_request_withdraw",
        owner="tenancy",
        response_model=ControllerPolicyAdoptionWithdrawView,
        responses={status: {"model": ErrorEnvelope} for status in (401, 403, 404, 409, 422)},
    )


def add_controller_policy_adoption_platform_routes(
    router: APIRouter,
    *,
    commands: ControllerPolicyAdoptionCommands,
    reader: ControllerPolicyAdoptionReader,
    authenticated_actor: Callable[[Request], Awaitable[PlatformActorContext]],
) -> None:
    async def list_adoptions(
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
        response: Response,
        after: Annotated[UUID | None, Query()] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> ControllerPolicyAdoptionPageView:
        require_platform_capability(actor, PLATFORM_READ)
        rows = await reader.list_adoptions(
            actor, ListControllerPolicyAdoptions(after=after, limit=limit + 1)
        )
        response.headers["Cache-Control"] = "no-store"
        page = rows[:limit]
        return ControllerPolicyAdoptionPageView(
            items=[_summary_view(row) for row in page],
            next_after=page[-1].request_id if len(rows) > limit else None,
        )

    async def review_adoption(
        request_id: UUID,
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
        response: Response,
    ) -> ControllerPolicyAdoptionReviewView:
        require_platform_capability(actor, PLATFORM_ADOPTION)
        review = await commands.get_review(actor, request_id)
        response.headers["Cache-Control"] = "no-store"
        return controller_policy_adoption_review_view(review)

    async def apply_adoption(
        request_id: UUID,
        body: ControllerPolicyAdoptionApplyBody,
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
        idempotency_key: AdoptionIdempotencyKey,
        response: Response,
    ) -> ControllerPolicyAdoptionAppliedView:
        require_platform_capability(actor, PLATFORM_ADOPTION)
        result = await commands.apply_adoption(
            actor,
            ApplyControllerPolicyAdoption(
                request_id=request_id,
                expected_request_revision=body.expected_request_revision,
                idempotency_key=idempotency_key,
            ),
        )
        response.headers["Cache-Control"] = "no-store"
        return ControllerPolicyAdoptionAppliedView(
            fact_id=result.fact_id,
            request_id=result.request_id,
            organization_id=result.organization_id,
            controller_principal_id=result.controller_principal_id,
            platform_approver_principal_id=result.platform_approver_principal_id,
            source_policy_key=result.source_policy_key,
            target_policy_key=result.target_policy_key,
            authority_revision_before=result.authority_revision_before,
            authority_revision_after=result.authority_revision_after,
            added_capabilities=result.added_capabilities,
            request_revision=result.request_revision,
        )

    add_capability_route(
        router,
        "/v1/platform/controller-policy-adoptions",
        list_adoptions,
        methods=["GET"],
        capability=PLATFORM_READ,
        operation_id="platform_controller_policy_adoption_list",
        owner="tenancy",
        response_model=ControllerPolicyAdoptionPageView,
        responses={status: {"model": ErrorEnvelope} for status in (401, 403, 422)},
    )
    add_capability_route(
        router,
        "/v1/platform/controller-policy-adoptions/{request_id}",
        review_adoption,
        methods=["GET"],
        capability=PLATFORM_ADOPTION,
        operation_id="platform_controller_policy_adoption_review",
        owner="tenancy",
        response_model=ControllerPolicyAdoptionReviewView,
        responses={status: {"model": ErrorEnvelope} for status in (401, 403, 404, 409)},
    )
    add_capability_route(
        router,
        "/v1/platform/controller-policy-adoptions/{request_id}:apply",
        apply_adoption,
        methods=["POST"],
        capability=PLATFORM_ADOPTION,
        operation_id="platform_controller_policy_adoption_apply",
        owner="tenancy",
        response_model=ControllerPolicyAdoptionAppliedView,
        responses={status: {"model": ErrorEnvelope} for status in (401, 403, 404, 409, 422)},
    )


def _summary_view(row: ControllerPolicyAdoptionSummary) -> ControllerPolicyAdoptionSummaryView:
    return ControllerPolicyAdoptionSummaryView(
        request_id=row.request_id,
        organization_id=row.organization_id,
        controller_principal_id=row.controller_principal_id,
        source_policy_key=row.source_policy_key,
        target_policy_key=row.target_policy_key,
        expected_authority_revision=row.expected_authority_revision,
        status=row.status,
        request_revision=row.request_revision,
        created_at=row.created_at,
        expires_at=row.expires_at,
    )


def controller_policy_adoption_review_view(
    row: ControllerPolicyAdoptionReview,
) -> ControllerPolicyAdoptionReviewView:
    return ControllerPolicyAdoptionReviewView(
        request_id=row.request.request_id,
        organization_id=row.request.organization_id,
        controller_principal_id=row.request.controller_principal_id,
        source_policy_key=row.request.source_policy_key,
        target_policy_key=row.request.target_policy_key,
        expected_authority_revision=row.request.expected_authority_revision,
        current_authority_revision=row.current_authority_revision,
        request_revision=row.request.request_revision,
        reason=row.reason,
        expires_at=row.request.expires_at,
        proposed_capabilities=row.proposed_capabilities,
        revoked_capabilities=row.revoked_capabilities,
        proposed_delta_does_not_restore_revoked_capabilities=not row.revoked_capabilities,
    )


def _detail_view(row: ControllerPolicyAdoptionDetail) -> ControllerPolicyAdoptionDetailView:
    return ControllerPolicyAdoptionDetailView(
        request_id=row.request_id,
        source_policy_key=row.source_policy_key,
        target_policy_key=row.target_policy_key,
        expected_authority_revision=row.expected_authority_revision,
        status=row.status,
        request_revision=row.request_revision,
        created_at=row.created_at,
        expires_at=row.expires_at,
        authority_revision_before=row.authority_revision_before,
        authority_revision_after=row.authority_revision_after,
        added_capabilities=row.added_capabilities,
    )


def add_controller_policy_adoption_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(
        ControllerPolicyAdoptionError, controller_policy_adoption_error_handler
    )


async def controller_policy_adoption_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, ControllerPolicyAdoptionForbidden):
        status, code, message, resolution = (
            403,
            "controller_policy_adoption_forbidden",
            "The current identity is not authorized for this policy adoption.",
            ErrorResolution.REQUEST_AUTHORITY,
        )
    elif isinstance(exc, ControllerPolicyAdoptionNotFound):
        status, code, message, resolution = (
            404,
            "controller_policy_adoption_not_found",
            "The policy adoption request is unavailable.",
            ErrorResolution.FIX_REQUEST,
        )
    elif isinstance(exc, ControllerPolicyAdoptionConsentInvalidated):
        status, code, message, resolution = (
            409,
            "controller_policy_adoption_consent_invalidated",
            "Native account recovery occurred after controller consent; request fresh consent.",
            ErrorResolution.REFRESH_AND_RETRY,
        )
    elif isinstance(exc, ControllerPolicyAdoptionConflict):
        status, code, message, resolution = (
            409,
            "controller_policy_adoption_conflict",
            "The policy adoption request is stale, closed, or conflicts with current authority.",
            ErrorResolution.REFRESH_AND_RETRY,
        )
    elif isinstance(exc, ControllerPolicyAdoptionInvalid):
        status, code, message, resolution = (
            422,
            "controller_policy_adoption_invalid",
            "The policy adoption request is invalid.",
            ErrorResolution.FIX_REQUEST,
        )
    else:
        status, code, message, resolution = (
            500,
            "controller_policy_adoption_failed",
            "The policy adoption command failed.",
            ErrorResolution.OPERATOR_INTERVENTION,
        )
    return JSONResponse(
        status_code=status,
        content=ErrorEnvelope(
            error=ErrorBody(code=code, message=message, resolution=resolution)
        ).model_dump(mode="json"),
        headers={"Cache-Control": "no-store"},
    )
