from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from request_engine.entrypoints.http.native_auth_errors import native_identity_input_error_response
from request_engine.platform.http.errors import ErrorEnvelope
from request_engine.platform.security.native_auth import (
    PasswordPolicyViolation,
    normalize_login_handle,
    parse_opaque_token,
)
from request_engine.platform.security.native_http import bearer_token
from request_engine.platform.security.native_human_auth import (
    NativeHumanAuthService,
    NativeIdentityAlreadyExists,
)
from request_engine.platform.security.native_session import (
    NativeSessionAuthenticator,
    NativeSessionEvidence,
)


class NativeEnrollmentBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    login_handle: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=1024, repr=False)

    @field_validator("login_handle")
    @classmethod
    def validate_handle(cls, value: str) -> str:
        return normalize_login_handle(value)


class NativeEnrollmentView(BaseModel):
    native_identity_id: UUID
    identity_authority_id: UUID
    login_handle: str


class NativeLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    login_handle: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=1024, repr=False)

    @field_validator("login_handle")
    @classmethod
    def validate_handle(cls, value: str) -> str:
        return normalize_login_handle(value)


class NativePasswordRotationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    login_handle: str = Field(min_length=1, max_length=320)
    current_password: str = Field(min_length=1, max_length=1024, repr=False)
    new_password: str = Field(min_length=1, max_length=1024, repr=False)

    @field_validator("login_handle")
    @classmethod
    def validate_handle(cls, value: str) -> str:
        return normalize_login_handle(value)


class NativeSessionResponse(BaseModel):
    access_token: str = Field(repr=False)
    token_type: str = "Bearer"
    expires_at: datetime


class NativeCredentialRotationResponse(BaseModel):
    credential_id: UUID


def create_native_auth_router(
    *,
    service: NativeHumanAuthService,
    authenticator: NativeSessionAuthenticator,
    identity_authority_id: UUID,
) -> APIRouter:
    router = APIRouter(prefix="/auth/native", tags=["Native authentication"])

    async def enroll_identity(
        payload: NativeEnrollmentBody,
        response: Response,
    ) -> NativeEnrollmentView | JSONResponse:
        try:
            enrolled = await service.enroll_password_identity(
                identity_authority_id=identity_authority_id,
                login_handle=payload.login_handle,
                password=payload.password,
            )
        except (NativeIdentityAlreadyExists, PasswordPolicyViolation) as exc:
            return native_identity_input_error_response(exc)
        _prevent_secret_caching(response)
        return NativeEnrollmentView(
            native_identity_id=enrolled.native_identity_id,
            identity_authority_id=identity_authority_id,
            login_handle=enrolled.login_handle,
        )

    async def create_session(
        payload: NativeLoginRequest,
        response: Response,
    ) -> NativeSessionResponse:
        issued = await service.authenticate_password(
            identity_authority_id=identity_authority_id,
            login_handle=payload.login_handle,
            password=payload.password,
        )
        _prevent_secret_caching(response)
        return NativeSessionResponse(
            access_token=issued.raw_token,
            expires_at=issued.expires_at,
        )

    async def revoke_current_session(request: Request, response: Response) -> None:
        raw_token = bearer_token(request)
        parsed = parse_opaque_token(raw_token)
        subject = await authenticator.authenticate(NativeSessionEvidence(raw_token))
        await service.revoke_session(
            native_identity_id=UUID(subject.subject_id),
            session_id=parsed.token_id,
        )
        _prevent_secret_caching(response)

    async def revoke_all_sessions(request: Request, response: Response) -> None:
        raw_token = bearer_token(request)
        subject = await authenticator.authenticate(NativeSessionEvidence(raw_token))
        await service.revoke_all_sessions(native_identity_id=UUID(subject.subject_id))
        _prevent_secret_caching(response)

    async def rotate_password(
        payload: NativePasswordRotationRequest,
        response: Response,
    ) -> NativeCredentialRotationResponse | JSONResponse:
        try:
            credential_id = await service.rotate_password(
                identity_authority_id=identity_authority_id,
                login_handle=payload.login_handle,
                current_password=payload.current_password,
                new_password=payload.new_password,
            )
        except PasswordPolicyViolation as exc:
            return native_identity_input_error_response(exc)
        _prevent_secret_caching(response)
        return NativeCredentialRotationResponse(credential_id=credential_id)

    router.add_api_route(
        "/identities",
        enroll_identity,
        methods=["POST"],
        operation_id="nativeIdentityEnroll",
        response_model=NativeEnrollmentView,
        status_code=status.HTTP_201_CREATED,
        summary="Enroll a native human identity without business authority",
        description=(
            "Creates a password identity in the server-configured native authority. "
            "Does not create a Principal, binding, membership, grants or session. "
            "Authenticate separately with POST /auth/native/sessions. Login handles are "
            "trimmed and case-folded; an already enrolled handle returns 409 and never "
            "replaces credentials. Enrollment is not an idempotency-key operation: "
            "after an uncertain response, attempt login before retrying enrollment. "
            "Passwords require at least 12 characters and at most 1024 UTF-8 bytes."
        ),
        responses={
            409: {"model": ErrorEnvelope, "description": "Native login handle already enrolled"},
            422: {"model": ErrorEnvelope, "description": "Invalid enrollment input or password"},
        },
    )
    router.add_api_route(
        "/sessions",
        create_session,
        methods=["POST"],
        operation_id="nativeSessionCreate",
        response_model=NativeSessionResponse,
        status_code=status.HTTP_201_CREATED,
    )
    router.add_api_route(
        "/sessions/current",
        revoke_current_session,
        methods=["DELETE"],
        operation_id="nativeSessionRevokeCurrent",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    router.add_api_route(
        "/sessions",
        revoke_all_sessions,
        methods=["DELETE"],
        operation_id="nativeSessionRevokeAll",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    router.add_api_route(
        "/password",
        rotate_password,
        methods=["PUT"],
        operation_id="nativePasswordRotate",
        response_model=NativeCredentialRotationResponse,
        responses={
            401: {"model": ErrorEnvelope, "description": "Current credential is invalid"},
            422: {"model": ErrorEnvelope, "description": "Invalid input or password policy"},
        },
    )
    return router


def _prevent_secret_caching(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
