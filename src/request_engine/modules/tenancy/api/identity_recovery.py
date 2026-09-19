from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request, Response, Security
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.tenancy.adapters.db.identity_recovery_commands import (
    PostgresIdentityRecoveryCommands,
)
from request_engine.modules.tenancy.adapters.db.identity_recovery_reader import (
    PostgresIdentityRecoveryReader,
)
from request_engine.modules.tenancy.application.commands.identity_recovery import (
    ApproveIdentityRecoveryCaseCommand,
    CreateIdentityRecoveryCaseCommand,
    IdentityRecoveryConflict,
    IdentityRecoveryError,
    IdentityRecoveryForbidden,
    IdentityRecoveryInvalid,
    IdentityRecoveryNotFound,
    IdentityRecoveryRevisionConflict,
    IdentityRecoveryUnavailable,
    IssueIdentityRecoveryCaseCommand,
    RevokeIdentityRecoveryCaseCommand,
)
from request_engine.modules.tenancy.application.queries.identity_recovery import (
    GetIdentityRecoveryCaseQuery,
    IdentityRecoveryCaseNotFound,
    IdentityRecoveryReadError,
    IdentityRecoveryReadForbidden,
    IdentityRecoveryReadInvalid,
    ListIdentityRecoveryCasesQuery,
)
from request_engine.modules.tenancy.application.queries.identity_recovery import (
    IdentityRecoveryCaseView as IdentityRecoveryCaseSummary,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope, ErrorResolution
from request_engine.platform.secrets.delivery import RecoverySecretDelivery
from request_engine.platform.security.platform_context import PlatformActorContext
from request_engine.platform.security.platform_http import PlatformActorResolver

_NativeBearer = Annotated[
    HTTPAuthorizationCredentials | None,
    Security(HTTPBearer(scheme_name="NativeSessionBearer", auto_error=False)),
]
_IdempotencyKey = Annotated[
    str, Header(alias="Idempotency-Key", min_length=1, max_length=200, pattern=r"\S")
]


class CreateIdentityRecoveryCaseBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    target_native_identity_id: UUID
    reason_code: str = Field(min_length=1, max_length=80)
    evidence_reference: str = Field(min_length=1, max_length=400)
    delivery_destination_reference: str = Field(min_length=1, max_length=200)


class ApproveIdentityRecoveryCaseBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_revision: int = Field(ge=1)
    reason_code: str = Field(min_length=1, max_length=80)


class IssueIdentityRecoveryCaseBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_revision: int = Field(ge=1)


class RevokeIdentityRecoveryCaseBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_revision: int = Field(ge=1)
    reason_code: str = Field(min_length=1, max_length=80)


class IdentityRecoveryCaseView(BaseModel):
    case_id: UUID
    target_native_identity_id: UUID
    status: str
    delivery_status: str
    revision: int
    issuance_generation: int
    approval_expires_at: datetime | None
    proof_expires_at: datetime | None
    created_at: datetime
    approved_at: datetime | None
    issued_at: datetime | None
    consumed_at: datetime | None
    revoked_at: datetime | None


class IdentityRecoveryCasePageView(BaseModel):
    items: list[IdentityRecoveryCaseView]
    next_after: UUID | None


async def identity_recovery_error_handler(_: Request, exc: Exception) -> JSONResponse:
    errors: dict[type[Exception], tuple[int, str, ErrorResolution]] = {
        IdentityRecoveryForbidden: (
            403,
            "platform_identity_recovery_forbidden",
            ErrorResolution.REQUEST_AUTHORITY,
        ),
        IdentityRecoveryReadForbidden: (
            403,
            "platform_identity_recovery_forbidden",
            ErrorResolution.REQUEST_AUTHORITY,
        ),
        IdentityRecoveryNotFound: (
            404,
            "platform_identity_recovery_case_not_found",
            ErrorResolution.FIX_REQUEST,
        ),
        IdentityRecoveryCaseNotFound: (
            404,
            "platform_identity_recovery_case_not_found",
            ErrorResolution.FIX_REQUEST,
        ),
        IdentityRecoveryConflict: (
            409,
            "platform_identity_recovery_conflict",
            ErrorResolution.FIX_REQUEST,
        ),
        IdentityRecoveryInvalid: (
            422,
            "platform_identity_recovery_invalid",
            ErrorResolution.FIX_REQUEST,
        ),
        IdentityRecoveryReadInvalid: (
            422,
            "platform_identity_recovery_invalid",
            ErrorResolution.FIX_REQUEST,
        ),
        IdentityRecoveryRevisionConflict: (
            409,
            "platform_identity_recovery_revision_conflict",
            ErrorResolution.REFRESH_AND_RETRY,
        ),
        IdentityRecoveryUnavailable: (
            503,
            "recovery_delivery_unconfigured",
            ErrorResolution.OPERATOR_INTERVENTION,
        ),
    }
    status_code, code, resolution = errors.get(
        type(exc),
        (
            500,
            "platform_identity_recovery_failed",
            ErrorResolution.OPERATOR_INTERVENTION,
        ),
    )
    return JSONResponse(
        status_code=status_code,
        content=ErrorEnvelope(
            error=ErrorBody(
                code=code,
                message="The platform identity recovery operation could not be accepted.",
                resolution=resolution,
                retryable=False,
            )
        ).model_dump(mode="json"),
        headers={"Cache-Control": "no-store"},
    )


def install_identity_recovery_http(
    app: FastAPI,
    *,
    read_session_factory: SessionFactory,
    write_session_factory: SessionFactory,
    actor_resolver: PlatformActorResolver,
    delivery: RecoverySecretDelivery | None,
) -> None:
    reader = PostgresIdentityRecoveryReader(read_session_factory)
    commands = PostgresIdentityRecoveryCommands(write_session_factory, delivery)
    router = APIRouter(tags=["Platform identity recovery"])

    async def authenticated_actor(request: Request) -> PlatformActorContext:
        return await actor_resolver.resolve_platform_actor(request)

    async def create_case(
        body: CreateIdentityRecoveryCaseBody,
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
        response: Response,
        _bearer: _NativeBearer,
        idempotency_key: _IdempotencyKey,
    ) -> IdentityRecoveryCaseView:
        result = await commands.create_case(
            actor,
            CreateIdentityRecoveryCaseCommand(
                target_native_identity_id=body.target_native_identity_id,
                reason_code=body.reason_code,
                evidence_reference=body.evidence_reference,
                delivery_destination_reference=body.delivery_destination_reference,
                idempotency_key=idempotency_key,
            ),
        )
        response.headers["Cache-Control"] = "no-store"
        return _view(result)

    async def list_cases(
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
        response: Response,
        _bearer: _NativeBearer,
        after: Annotated[UUID | None, Query()] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> IdentityRecoveryCasePageView:
        rows = await reader.list_cases(
            actor, ListIdentityRecoveryCasesQuery(after=after, limit=limit)
        )
        response.headers["Cache-Control"] = "no-store"
        return IdentityRecoveryCasePageView(
            items=[_view(row) for row in rows],
            next_after=rows[-1].case_id if len(rows) == limit else None,
        )

    async def get_case(
        case_id: UUID,
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
        response: Response,
        _bearer: _NativeBearer,
    ) -> IdentityRecoveryCaseView:
        row = await reader.get_case(actor, GetIdentityRecoveryCaseQuery(case_id))
        if row is None:
            raise IdentityRecoveryCaseNotFound("identity recovery case is not addressable")
        response.headers["Cache-Control"] = "no-store"
        return _view(row)

    async def approve_case(
        case_id: UUID,
        body: ApproveIdentityRecoveryCaseBody,
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
        response: Response,
        _bearer: _NativeBearer,
        idempotency_key: _IdempotencyKey,
    ) -> IdentityRecoveryCaseView:
        result = await commands.approve_case(
            actor,
            ApproveIdentityRecoveryCaseCommand(
                case_id=case_id,
                expected_revision=body.expected_revision,
                reason_code=body.reason_code,
                idempotency_key=idempotency_key,
            ),
        )
        response.headers["Cache-Control"] = "no-store"
        return _view(result)

    async def issue_case(
        case_id: UUID,
        body: IssueIdentityRecoveryCaseBody,
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
        response: Response,
        _bearer: _NativeBearer,
        idempotency_key: _IdempotencyKey,
    ) -> IdentityRecoveryCaseView:
        result = await commands.issue_case(
            actor,
            IssueIdentityRecoveryCaseCommand(
                case_id=case_id,
                expected_revision=body.expected_revision,
                idempotency_key=idempotency_key,
            ),
        )
        response.headers["Cache-Control"] = "no-store"
        return _view(result)

    async def revoke_case(
        case_id: UUID,
        body: RevokeIdentityRecoveryCaseBody,
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
        response: Response,
        _bearer: _NativeBearer,
        idempotency_key: _IdempotencyKey,
    ) -> IdentityRecoveryCaseView:
        result = await commands.revoke_case(
            actor,
            RevokeIdentityRecoveryCaseCommand(
                case_id=case_id,
                expected_revision=body.expected_revision,
                reason_code=body.reason_code,
                idempotency_key=idempotency_key,
            ),
        )
        response.headers["Cache-Control"] = "no-store"
        return _view(result)

    read_responses = {status: {"model": ErrorEnvelope} for status in (400, 401, 403, 422)}
    case_responses = {**read_responses, 404: {"model": ErrorEnvelope}}
    mutation_responses = {**case_responses, 409: {"model": ErrorEnvelope}}
    add_capability_route(
        router,
        "/v1/platform/identity-recovery-cases",
        create_case,
        capability="platform.identity.recover",
        methods=["POST"],
        operation_id="platform_identity_recovery_case_create",
        owner="tenancy",
        response_model=IdentityRecoveryCaseView,
        status_code=201,
        responses={**mutation_responses, 503: {"model": ErrorEnvelope}},
    )
    add_capability_route(
        router,
        "/v1/platform/identity-recovery-cases",
        list_cases,
        capability="platform.identity.read",
        methods=["GET"],
        operation_id="platform_identity_recovery_case_list",
        owner="tenancy",
        response_model=IdentityRecoveryCasePageView,
        responses=read_responses,
    )
    add_capability_route(
        router,
        "/v1/platform/identity-recovery-cases/{case_id}",
        get_case,
        capability="platform.identity.read",
        methods=["GET"],
        operation_id="platform_identity_recovery_case_get",
        owner="tenancy",
        response_model=IdentityRecoveryCaseView,
        responses=case_responses,
    )
    add_capability_route(
        router,
        "/v1/platform/identity-recovery-cases/{case_id}:approve",
        approve_case,
        capability="platform.identity.recovery_approve",
        methods=["POST"],
        operation_id="platform_identity_recovery_case_approve",
        owner="tenancy",
        response_model=IdentityRecoveryCaseView,
        responses=mutation_responses,
    )
    add_capability_route(
        router,
        "/v1/platform/identity-recovery-cases/{case_id}:issue",
        issue_case,
        capability="platform.identity.recover",
        methods=["POST"],
        operation_id="platform_identity_recovery_case_issue",
        owner="tenancy",
        response_model=IdentityRecoveryCaseView,
        status_code=202,
        responses={**mutation_responses, 503: {"model": ErrorEnvelope}},
    )
    add_capability_route(
        router,
        "/v1/platform/identity-recovery-cases/{case_id}:revoke",
        revoke_case,
        capability="platform.identity.recover",
        methods=["POST"],
        operation_id="platform_identity_recovery_case_revoke",
        owner="tenancy",
        response_model=IdentityRecoveryCaseView,
        responses=mutation_responses,
    )
    app.add_exception_handler(IdentityRecoveryError, identity_recovery_error_handler)
    app.add_exception_handler(IdentityRecoveryReadError, identity_recovery_error_handler)
    app.include_router(router)


def _view(row: IdentityRecoveryCaseSummary) -> IdentityRecoveryCaseView:
    return IdentityRecoveryCaseView(
        case_id=row.case_id,
        target_native_identity_id=row.target_native_identity_id,
        status=row.status,
        delivery_status=row.delivery_status,
        revision=row.revision,
        issuance_generation=row.issuance_generation,
        approval_expires_at=row.approval_expires_at,
        proof_expires_at=row.proof_expires_at,
        created_at=row.created_at,
        approved_at=row.approved_at,
        issued_at=row.issued_at,
        consumed_at=row.consumed_at,
        revoked_at=row.revoked_at,
    )
