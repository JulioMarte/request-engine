from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from request_engine.entrypoints.http.native_auth_errors import (
    native_enrollment_unavailable_response,
    native_identity_input_error_response,
    native_recovery_error_response,
)
from request_engine.platform.http.errors import ErrorEnvelope
from request_engine.platform.security.authentication import AuthenticatedSubject
from request_engine.platform.security.freshness import REAUTHENTICATION_WINDOW
from request_engine.platform.security.native_auth import (
    CredentialInvalid,
    NativeAuthenticationError,
    PasswordPolicyViolation,
    normalize_login_handle,
    parse_opaque_token,
)
from request_engine.platform.security.native_http import bearer_token
from request_engine.platform.security.native_human_auth import (
    NativeEnrollmentUnavailable,
    NativeHumanAuthService,
    NativeIdentityAlreadyExists,
    RecoveryIntentInvalid,
)
from request_engine.platform.security.native_session import (
    NativeSessionAuthenticator,
    NativeSessionEvidence,
)
from request_engine.platform.security.native_webauthn_auth import (
    NativeWebAuthnAuthService,
    WebAuthnCeremonyError,
)
from request_engine.platform.security.native_webauthn_login import NativeWebAuthnLoginService
from request_engine.platform.security.webauthn import WebAuthnInputError, public_key_to_json


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


class NativePasswordRecoveryBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recovery_token: str = Field(min_length=1, max_length=1024, repr=False)
    new_password: str = Field(min_length=1, max_length=1024, repr=False)


class NativeSessionReauthBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=1, max_length=1024, repr=False)


class NativeSessionReauthView(BaseModel):
    authenticated_at: datetime
    reauth_expires_at: datetime


class NativeWebAuthnLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    login_handle: str = Field(min_length=1, max_length=320)

    @field_validator("login_handle")
    @classmethod
    def validate_handle(cls, value: str) -> str:
        return normalize_login_handle(value)


class NativeWebAuthnOptionsView(BaseModel):
    public_key: dict[str, Any]


class NativeWebAuthnLoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    login_handle: str = Field(min_length=1, max_length=320)
    credential: dict[str, Any]

    @field_validator("login_handle")
    @classmethod
    def validate_handle(cls, value: str) -> str:
        return normalize_login_handle(value)


class NativeWebAuthnStepUpBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credential: dict[str, Any]


class NativeWebAuthnStepUpView(BaseModel):
    authenticated_at: datetime
    authentication_assurance: str
    user_verified: bool


def create_native_auth_router(
    *,
    service: NativeHumanAuthService,
    authenticator: NativeSessionAuthenticator,
    identity_authority_id: UUID,
    webauthn_login: NativeWebAuthnLoginService | None = None,
    webauthn_auth: NativeWebAuthnAuthService | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/auth/native", tags=["Native authentication"])
    if (webauthn_login is None) != (webauthn_auth is None):
        raise ValueError("WebAuthn login and step-up must be composed together")

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
        except NativeEnrollmentUnavailable:
            return native_enrollment_unavailable_response()
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

    async def recover_password(payload: NativePasswordRecoveryBody) -> Response:
        try:
            await service.consume_recovery(
                raw_token=payload.recovery_token,
                new_password=payload.new_password,
            )
        except PasswordPolicyViolation as exc:
            return native_identity_input_error_response(exc)
        except (RecoveryIntentInvalid, NativeAuthenticationError):
            return native_recovery_error_response()
        response = Response(status_code=status.HTTP_204_NO_CONTENT)
        _prevent_secret_caching(response)
        return response

    async def reauthenticate_current_session(
        payload: NativeSessionReauthBody,
        request: Request,
        response: Response,
    ) -> NativeSessionReauthView:
        raw_token = bearer_token(request)
        parsed = parse_opaque_token(raw_token)
        subject = await authenticator.authenticate(NativeSessionEvidence(raw_token))
        authenticated_at = await service.reauthenticate_session(
            session_id=parsed.token_id,
            credential_id=_session_credential_id(subject),
            password=payload.password,
        )
        _prevent_secret_caching(response)
        return NativeSessionReauthView(
            authenticated_at=authenticated_at,
            reauth_expires_at=authenticated_at + REAUTHENTICATION_WINDOW,
        )

    async def webauthn_authentication_options(
        payload: NativeWebAuthnLoginRequest,
        response: Response,
    ) -> NativeWebAuthnOptionsView:
        assert webauthn_login is not None
        started = await webauthn_login.begin_login(
            identity_authority_id=identity_authority_id,
            login_handle=payload.login_handle,
        )
        _prevent_secret_caching(response)
        return NativeWebAuthnOptionsView(public_key=public_key_to_json(dict(started.public_key)))

    async def webauthn_create_session(
        payload: NativeWebAuthnLoginBody,
        response: Response,
    ) -> NativeSessionResponse:
        assert webauthn_login is not None
        try:
            issued = await webauthn_login.complete_login(
                identity_authority_id=identity_authority_id,
                login_handle=payload.login_handle,
                credential=payload.credential,
            )
        except (WebAuthnCeremonyError, WebAuthnInputError) as exc:
            raise CredentialInvalid("native WebAuthn authentication was rejected") from exc
        _prevent_secret_caching(response)
        return NativeSessionResponse(
            access_token=issued.raw_token,
            expires_at=issued.expires_at,
        )

    async def webauthn_step_up_options(
        request: Request,
        response: Response,
    ) -> NativeWebAuthnOptionsView:
        assert webauthn_auth is not None
        raw_token = bearer_token(request)
        parsed = parse_opaque_token(raw_token)
        await authenticator.authenticate(NativeSessionEvidence(raw_token))
        started = await webauthn_auth.begin_step_up(session_id=parsed.token_id)
        _prevent_secret_caching(response)
        return NativeWebAuthnOptionsView(public_key=public_key_to_json(dict(started.public_key)))

    async def webauthn_step_up(
        payload: NativeWebAuthnStepUpBody,
        request: Request,
        response: Response,
    ) -> NativeWebAuthnStepUpView:
        assert webauthn_auth is not None
        raw_token = bearer_token(request)
        parsed = parse_opaque_token(raw_token)
        subject = await authenticator.authenticate(NativeSessionEvidence(raw_token))
        try:
            await webauthn_auth.complete_step_up(
                session_id=parsed.token_id,
                native_identity_id=UUID(subject.subject_id),
                credential=payload.credential,
            )
        except (WebAuthnCeremonyError, WebAuthnInputError) as exc:
            raise CredentialInvalid("native WebAuthn step-up was rejected") from exc
        # Re-read the session so the response reflects the trusted post-step-up
        # evidence rather than anything the caller supplied.
        updated = await authenticator.authenticate(NativeSessionEvidence(raw_token))
        _prevent_secret_caching(response)
        return NativeWebAuthnStepUpView(
            authenticated_at=datetime.fromisoformat(updated.metadata["authenticated_at"]),
            authentication_assurance=updated.metadata["authentication_assurance"],
            user_verified=updated.metadata["user_verified"] == "true",
        )

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
            "If the configured native authority is unavailable, the deployment returns "
            "503 and an operator must restore it; retrying does not create the identity. "
            "Passwords require at least 12 characters and at most 1024 UTF-8 bytes."
        ),
        responses={
            409: {"model": ErrorEnvelope, "description": "Native login handle already enrolled"},
            422: {"model": ErrorEnvelope, "description": "Invalid enrollment input or password"},
            503: {
                "model": ErrorEnvelope,
                "description": "Native identity authority unavailable",
            },
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
        "/sessions:reauth",
        reauthenticate_current_session,
        methods=["POST"],
        operation_id="nativeSessionReauthenticate",
        response_model=NativeSessionReauthView,
        status_code=status.HTTP_200_OK,
        summary="Refresh the reauthentication freshness of the current native session",
        description=(
            "Verifies the current session's password again and advances its "
            "last_authenticated_at freshness basis. The session, identity, "
            "credential and authority must all still be active. An invalid "
            "password or unusable session returns the same opaque 401 as the "
            "other native authentication routes."
        ),
        responses={
            401: {"model": ErrorEnvelope, "description": "Session or password is invalid"},
            422: {"model": ErrorEnvelope, "description": "Invalid input"},
        },
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
    router.add_api_route(
        "/password:recover",
        recover_password,
        methods=["POST"],
        operation_id="nativePasswordRecover",
        status_code=status.HTTP_204_NO_CONTENT,
        response_model=None,
        summary="Replace a native password using a one-time recovery proof",
        description=(
            "Consumes an already issued recovery token, replaces the credential and "
            "invalidates existing sessions atomically. Does not issue a new session, "
            "create a binding, restore business grants or reactivate a disabled identity. "
            "The token determines the identity; identity and tenant selectors are not accepted. "
            "This endpoint never issues recovery tokens. After an ambiguous response, "
            "attempt login with the new password instead of blindly retrying the token."
        ),
        responses={
            401: {"model": ErrorEnvelope, "description": "Recovery proof unavailable or invalid"},
            422: {"model": ErrorEnvelope, "description": "Invalid input or password policy"},
        },
    )
    if webauthn_login is not None:
        _register_webauthn_routes(
            router,
            authentication_options=webauthn_authentication_options,
            create_session=webauthn_create_session,
            step_up_options=webauthn_step_up_options,
            step_up=webauthn_step_up,
        )
    return router


def _register_webauthn_routes(
    router: APIRouter,
    *,
    authentication_options: Any,
    create_session: Any,
    step_up_options: Any,
    step_up: Any,
) -> None:
    router.add_api_route(
        "/webauthn/authentication-options",
        authentication_options,
        methods=["POST"],
        operation_id="nativeWebAuthnAuthenticationOptions",
        response_model=NativeWebAuthnOptionsView,
        status_code=status.HTTP_200_OK,
        summary="Begin a native WebAuthn authentication ceremony",
        description=(
            "Returns a bounded one-time challenge and a credential allow-list for "
            "the supplied login handle. An unknown handle, a handle without an "
            "active passkey and a handle with passkeys all return the same response "
            "shape, so this endpoint is not a reliable account-enumeration oracle. "
            "The challenge is single-use and expires; it must be completed with "
            "POST /auth/native/webauthn/sessions."
        ),
        responses={
            422: {"model": ErrorEnvelope, "description": "Invalid input"},
        },
    )
    router.add_api_route(
        "/webauthn/sessions",
        create_session,
        methods=["POST"],
        operation_id="nativeWebAuthnSessionCreate",
        response_model=NativeSessionResponse,
        status_code=status.HTTP_201_CREATED,
        summary="Verify a WebAuthn assertion and issue a native session",
        description=(
            "Verifies the assertion against the one-time challenge, the stored "
            "credential, the relying-party/origin policy and user verification. "
            "Assurance, user verification and methods are derived only from the "
            "verified ceremony and cannot be supplied by the caller. A successful "
            "user-verified assertion issues a fresh session with "
            "PHISHING_RESISTANT assurance."
        ),
        responses={
            401: {"model": ErrorEnvelope, "description": "Assertion or credential is invalid"},
            422: {"model": ErrorEnvelope, "description": "Invalid input"},
        },
    )
    router.add_api_route(
        "/sessions/current/webauthn/step-up-options",
        step_up_options,
        methods=["POST"],
        operation_id="nativeWebAuthnStepUpOptions",
        response_model=NativeWebAuthnOptionsView,
        status_code=status.HTTP_200_OK,
        summary="Begin a WebAuthn step-up for the current native session",
        description=(
            "Returns a bounded step-up challenge bound to the bearer's session. "
            "The session and identity come only from the authenticated bearer; "
            "callers cannot select a target session or identity."
        ),
        responses={
            401: {"model": ErrorEnvelope, "description": "Session is invalid or unusable"},
            422: {"model": ErrorEnvelope, "description": "Invalid input"},
        },
    )
    router.add_api_route(
        "/sessions/current/webauthn/step-up",
        step_up,
        methods=["POST"],
        operation_id="nativeWebAuthnStepUp",
        response_model=NativeWebAuthnStepUpView,
        status_code=status.HTTP_200_OK,
        summary="Complete a WebAuthn step-up for the current native session",
        description=(
            "Verifies a session-bound assertion and raises the session's trusted "
            "authentication evidence. The credential must belong to the session's "
            "native identity, the challenge must belong to the session, and user "
            "verification must be accepted. A recovery-derived session stays "
            "RECOVERY and cannot become phishing-resistant through step-up."
        ),
        responses={
            401: {"model": ErrorEnvelope, "description": "Assertion or credential is invalid"},
            422: {"model": ErrorEnvelope, "description": "Invalid input"},
        },
    )


def _prevent_secret_caching(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


def _session_credential_id(subject: AuthenticatedSubject) -> UUID:
    value = subject.metadata.get("credential_id")
    if value is None:
        raise CredentialInvalid("native session credential is invalid")
    try:
        return UUID(value)
    except ValueError as exc:
        raise CredentialInvalid("native session credential is invalid") from exc
