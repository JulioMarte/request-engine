from __future__ import annotations

from datetime import UTC, datetime
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
from request_engine.platform.security.assurance import AuthenticationAssurance
from request_engine.platform.security.authentication import AuthenticatedSubject
from request_engine.platform.security.freshness import (
    REAUTHENTICATION_WINDOW,
    PhishingResistantAuthenticationRequired,
    RecentAuthenticationRequired,
)
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
from request_engine.platform.security.native_recovery_addresses import (
    NativeRecoveryAddressDeliveryUnavailable,
    NativeRecoveryAddressInvalid,
    NativeRecoveryAddressService,
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
from request_engine.platform.security.recovery_codes import (
    NativeRecoveryCodeService,
    RecoveryCodeInvalid,
)
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


class NativeRecoveryCodePasswordResetBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recovery_code: str = Field(min_length=16, max_length=256, repr=False)
    new_password: str = Field(min_length=1, max_length=1024, repr=False)


class NativeSessionReauthBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=1, max_length=1024, repr=False)


class NativeSessionReauthView(BaseModel):
    authenticated_at: datetime
    reauth_expires_at: datetime


class NativeSessionCurrentView(BaseModel):
    authenticated_at: datetime
    authentication_methods: list[str]
    authentication_assurance: str
    user_verified: bool
    recovery_derived: bool
    recovery_restricted: bool


class NativeRecoveryReadinessView(BaseModel):
    recovery_state: str
    recovery_epoch: int
    last_recovered_at: datetime | None
    last_recovery_method: str | None
    completed_at: datetime | None
    active_code_set: bool
    remaining_codes: int
    active_webauthn_credentials: int


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


class NativeWebAuthnRegistrationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credential: dict[str, Any]


class NativeWebAuthnRegistrationView(BaseModel):
    credential_id: UUID


class NativeRecoveryCodesView(BaseModel):
    codes: list[str]


class NativeRecoveryAddressCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)


class NativeRecoveryAddressVerifyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verification_token: str = Field(min_length=1, max_length=1024, repr=False)


class NativeRecoveryRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    login_handle: str = Field(min_length=1, max_length=320)


class NativeRecoveryAddressView(BaseModel):
    recovery_address_id: UUID
    kind: str
    address: str
    status: str
    revision: int
    verified_at: datetime | None
    created_at: datetime


class NativeRecoveryAddressPreparedView(BaseModel):
    recovery_address_id: UUID
    status: str
    verification_created: bool


def create_native_auth_router(
    *,
    service: NativeHumanAuthService,
    authenticator: NativeSessionAuthenticator,
    identity_authority_id: UUID,
    webauthn_login: NativeWebAuthnLoginService | None = None,
    webauthn_auth: NativeWebAuthnAuthService | None = None,
    recovery_codes: NativeRecoveryCodeService | None = None,
    recovery_addresses: NativeRecoveryAddressService | None = None,
    allow_identity_enrollment: bool = True,
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

    async def recover_password_with_code(
        payload: NativeRecoveryCodePasswordResetBody,
    ) -> Response | JSONResponse:
        if recovery_codes is None:
            raise RuntimeError("offline recovery-code reset is not composed")
        try:
            await recovery_codes.recover_password(
                code=payload.recovery_code,
                new_password=payload.new_password,
            )
        except PasswordPolicyViolation as exc:
            return native_identity_input_error_response(exc)
        except RecoveryCodeInvalid:
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

    async def read_current_session(
        request: Request,
        response: Response,
    ) -> NativeSessionCurrentView:
        raw_token = bearer_token(request)
        subject = await authenticator.authenticate(NativeSessionEvidence(raw_token))
        methods = [
            method
            for method in subject.metadata.get("authentication_methods", "").split(",")
            if method
        ]
        _prevent_secret_caching(response)
        return NativeSessionCurrentView(
            authenticated_at=datetime.fromisoformat(subject.metadata["authenticated_at"]),
            authentication_methods=methods,
            authentication_assurance=subject.metadata["authentication_assurance"],
            user_verified=subject.metadata["user_verified"] == "true",
            recovery_derived=subject.metadata["recovery_derived"] == "true",
            recovery_restricted=subject.metadata.get("recovery_restricted") == "true",
        )

    async def read_recovery_readiness(
        request: Request,
        response: Response,
    ) -> NativeRecoveryReadinessView:
        if recovery_codes is None:
            raise RuntimeError("recovery-code lifecycle is not composed")
        raw_token = bearer_token(request)
        subject = await authenticator.authenticate(NativeSessionEvidence(raw_token))
        readiness = await recovery_codes.readiness(native_identity_id=UUID(subject.subject_id))
        _prevent_secret_caching(response)
        return NativeRecoveryReadinessView(
            recovery_state=readiness.recovery_state,
            recovery_epoch=readiness.recovery_epoch,
            last_recovered_at=readiness.last_recovered_at,
            last_recovery_method=readiness.last_recovery_method,
            completed_at=readiness.completed_at,
            active_code_set=readiness.active_code_set,
            remaining_codes=readiness.remaining_codes,
            active_webauthn_credentials=readiness.active_webauthn_credentials,
        )

    async def complete_recovery(
        request: Request,
        response: Response,
    ) -> NativeRecoveryReadinessView:
        if recovery_codes is None:
            raise RuntimeError("recovery-code lifecycle is not composed")
        raw_token = bearer_token(request)
        subject = await authenticator.authenticate(NativeSessionEvidence(raw_token))
        _require_recent_phishing_resistant_subject(subject)
        readiness = await recovery_codes.complete_recovery(
            native_identity_id=UUID(subject.subject_id)
        )
        _prevent_secret_caching(response)
        return NativeRecoveryReadinessView(
            recovery_state=readiness.recovery_state,
            recovery_epoch=readiness.recovery_epoch,
            last_recovered_at=readiness.last_recovered_at,
            last_recovery_method=readiness.last_recovery_method,
            completed_at=readiness.completed_at,
            active_code_set=readiness.active_code_set,
            remaining_codes=readiness.remaining_codes,
            active_webauthn_credentials=readiness.active_webauthn_credentials,
        )

    async def prepare_recovery_address(
        payload: NativeRecoveryAddressCreateBody,
        request: Request,
        response: Response,
    ) -> NativeRecoveryAddressPreparedView | JSONResponse:
        if recovery_addresses is None:
            raise RuntimeError("verified recovery addresses are not composed")
        raw_token = bearer_token(request)
        subject = await authenticator.authenticate(NativeSessionEvidence(raw_token))
        _require_recent_phishing_resistant_subject(subject)
        try:
            prepared = await recovery_addresses.prepare_email(
                native_identity_id=UUID(subject.subject_id),
                address=payload.email,
            )
        except NativeRecoveryAddressInvalid:
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                content={
                    "error": {
                        "code": "recovery_address_invalid",
                        "message": "the recovery address is invalid",
                        "retryable": False,
                        "resolution": "fix_request",
                    }
                },
                headers={"Cache-Control": "no-store"},
            )
        except NativeRecoveryAddressDeliveryUnavailable:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={
                    "error": {
                        "code": "recovery_address_delivery_unavailable",
                        "message": "recovery-address verification delivery is unavailable",
                        "retryable": True,
                        "resolution": "retry_same_request",
                    }
                },
                headers={"Cache-Control": "no-store"},
            )
        _prevent_secret_caching(response)
        return NativeRecoveryAddressPreparedView(
            recovery_address_id=prepared.address_id,
            status=prepared.status,
            verification_created=prepared.verification_created,
        )

    async def list_recovery_addresses(
        request: Request,
        response: Response,
    ) -> list[NativeRecoveryAddressView]:
        if recovery_addresses is None:
            raise RuntimeError("verified recovery addresses are not composed")
        raw_token = bearer_token(request)
        subject = await authenticator.authenticate(NativeSessionEvidence(raw_token))
        rows = await recovery_addresses.list_for_identity(
            native_identity_id=UUID(subject.subject_id)
        )
        _prevent_secret_caching(response)
        return [
            NativeRecoveryAddressView(
                recovery_address_id=row.address_id,
                kind=row.kind,
                address=row.normalized_address,
                status=row.status,
                revision=row.revision,
                verified_at=row.verified_at,
                created_at=row.created_at,
            )
            for row in rows
        ]

    async def revoke_recovery_address(
        recovery_address_id: UUID,
        request: Request,
        response: Response,
    ) -> None | JSONResponse:
        if recovery_addresses is None:
            raise RuntimeError("verified recovery addresses are not composed")
        raw_token = bearer_token(request)
        subject = await authenticator.authenticate(NativeSessionEvidence(raw_token))
        _require_recent_phishing_resistant_subject(subject)
        try:
            await recovery_addresses.revoke(
                native_identity_id=UUID(subject.subject_id),
                address_id=recovery_address_id,
            )
        except NativeRecoveryAddressInvalid:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={
                    "error": {
                        "code": "recovery_address_not_found",
                        "message": "the recovery address is unavailable",
                        "retryable": False,
                        "resolution": "fix_request",
                    }
                },
                headers={"Cache-Control": "no-store"},
            )
        _prevent_secret_caching(response)

    async def verify_recovery_address(
        payload: NativeRecoveryAddressVerifyBody,
    ) -> Response | JSONResponse:
        if recovery_addresses is None:
            raise RuntimeError("verified recovery addresses are not composed")
        try:
            await recovery_addresses.verify(raw_token=payload.verification_token)
        except NativeRecoveryAddressInvalid:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "error": {
                        "code": "recovery_address_verification_invalid",
                        "message": "the recovery-address proof is invalid or expired",
                        "retryable": False,
                        "resolution": "reauthenticate",
                    }
                },
                headers={"Cache-Control": "no-store"},
            )
        response = Response(status_code=status.HTTP_204_NO_CONTENT)
        _prevent_secret_caching(response)
        return response

    async def request_verified_channel_recovery(
        payload: NativeRecoveryRequestBody,
    ) -> Response:
        if recovery_addresses is not None:
            await recovery_addresses.request_recovery(
                identity_authority_id=identity_authority_id,
                login_handle=payload.login_handle,
            )
        # Deliberately identical for unknown identities, missing verified
        # destinations and unconfigured/failed delivery.
        response = Response(status_code=status.HTTP_202_ACCEPTED)
        _prevent_secret_caching(response)
        return response

    async def webauthn_registration_options(
        request: Request,
        response: Response,
    ) -> NativeWebAuthnOptionsView:
        assert webauthn_auth is not None
        raw_token = bearer_token(request)
        subject = await authenticator.authenticate(NativeSessionEvidence(raw_token))
        started = await webauthn_auth.begin_registration(
            native_identity_id=UUID(subject.subject_id)
        )
        _prevent_secret_caching(response)
        return NativeWebAuthnOptionsView(public_key=public_key_to_json(dict(started.public_key)))

    async def webauthn_register_current_identity(
        payload: NativeWebAuthnRegistrationBody,
        request: Request,
        response: Response,
    ) -> NativeWebAuthnRegistrationView:
        assert webauthn_auth is not None
        raw_token = bearer_token(request)
        subject = await authenticator.authenticate(NativeSessionEvidence(raw_token))
        native_identity_id = UUID(subject.subject_id)
        try:
            credential_id = await webauthn_auth.complete_registration(
                credential=payload.credential,
                native_identity_id=native_identity_id,
            )
        except (WebAuthnCeremonyError, WebAuthnInputError) as exc:
            raise CredentialInvalid("native WebAuthn registration was rejected") from exc
        _prevent_secret_caching(response)
        return NativeWebAuthnRegistrationView(credential_id=credential_id)

    async def issue_current_recovery_codes(
        request: Request,
        response: Response,
    ) -> NativeRecoveryCodesView:
        if recovery_codes is None:
            raise RuntimeError("recovery-code lifecycle is not composed")
        raw_token = bearer_token(request)
        subject = await authenticator.authenticate(NativeSessionEvidence(raw_token))
        _require_recent_phishing_resistant_subject(subject)
        codes = await recovery_codes.issue_for_identity(native_identity_id=UUID(subject.subject_id))
        _prevent_secret_caching(response)
        return NativeRecoveryCodesView(codes=list(codes))

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

    if allow_identity_enrollment:
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
                409: {
                    "model": ErrorEnvelope,
                    "description": "Native login handle already enrolled",
                },
                422: {
                    "model": ErrorEnvelope,
                    "description": "Invalid enrollment input or password",
                },
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
        "/sessions/current",
        read_current_session,
        methods=["GET"],
        operation_id="nativeSessionReadCurrent",
        response_model=NativeSessionCurrentView,
        status_code=status.HTTP_200_OK,
        summary="Read the current native session's trusted authentication evidence",
        description=(
            "Returns the caller's own session evidence: proven methods, derived "
            "assurance, user verification, recovery-derived flag and the trusted "
            "authentication time. The session is taken only from the bearer; the "
            "request cannot select a session, identity, assurance or method. "
            "Assurance is derived from the verified ceremony that produced or "
            "refreshed the session, never from the presence of a credential."
        ),
        responses={
            401: {"model": ErrorEnvelope, "description": "Session is invalid or unusable"},
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
    if recovery_codes is not None:
        router.add_api_route(
            "/password:recover-with-code",
            recover_password_with_code,
            methods=["POST"],
            operation_id="nativePasswordRecoverWithRecoveryCode",
            status_code=status.HTTP_204_NO_CONTENT,
            response_model=None,
            summary="Replace a native password using an offline recovery code",
            description=(
                "Consumes one previously issued recovery code and atomically replaces "
                "the owning native identity's password. The code itself identifies the "
                "identity; callers cannot select a user. All active native sessions and "
                "pending recovery intents are revoked. The operation does not require "
                "SMTP, OpenBao/Vault, the previous password or a live WebAuthn credential, "
                "and never returns the previous password or a new session."
            ),
            responses={
                401: {"model": ErrorEnvelope, "description": "Recovery code is invalid or used"},
                422: {"model": ErrorEnvelope, "description": "Invalid input or password policy"},
            },
        )
    if recovery_codes is not None:
        router.add_api_route(
            "/sessions/current/recovery-readiness",
            read_recovery_readiness,
            methods=["GET"],
            operation_id="nativeRecoveryReadinessReadCurrent",
            response_model=NativeRecoveryReadinessView,
            summary="Read recovery readiness for the current native identity",
            responses={401: {"model": ErrorEnvelope, "description": "Session is invalid"}},
        )
        router.add_api_route(
            "/sessions/current/recovery:complete",
            complete_recovery,
            methods=["POST"],
            operation_id="nativeRecoveryCompleteCurrent",
            response_model=NativeRecoveryReadinessView,
            summary="Complete a restricted recovery after strong re-authentication",
            description=(
                "Requires a recent phishing-resistant session for the same native identity. "
                "It changes only recovery posture and never creates, restores or elevates "
                "Principal authority, bindings, memberships or grants."
            ),
            responses={
                401: {"model": ErrorEnvelope, "description": "Session is invalid"},
                403: {
                    "model": ErrorEnvelope,
                    "description": "Strong recovery completion proof required",
                },
            },
        )
        router.add_api_route(
            "/sessions/current/recovery-codes",
            issue_current_recovery_codes,
            methods=["POST"],
            operation_id="nativeCurrentRecoveryCodesIssue",
            response_model=NativeRecoveryCodesView,
            status_code=status.HTTP_201_CREATED,
            summary="Issue offline recovery codes for the current native identity",
            description=(
                "Requires a recent phishing-resistant session. The authenticated bearer "
                "determines the identity. Plaintext codes are returned once and only "
                "digests are persisted."
            ),
            responses={
                401: {"model": ErrorEnvelope, "description": "Session is invalid"},
                403: {"model": ErrorEnvelope, "description": "Strong recent proof required"},
            },
        )
        router.add_api_route(
            "/sessions/current/recovery-codes:regenerate",
            issue_current_recovery_codes,
            methods=["POST"],
            operation_id="nativeCurrentRecoveryCodesRegenerate",
            response_model=NativeRecoveryCodesView,
            status_code=status.HTTP_201_CREATED,
            summary="Regenerate offline recovery codes for the current native identity",
            responses={
                401: {"model": ErrorEnvelope, "description": "Session is invalid"},
                403: {"model": ErrorEnvelope, "description": "Strong recent proof required"},
            },
        )
    if recovery_addresses is not None:
        router.add_api_route(
            "/sessions/current/recovery-addresses",
            prepare_recovery_address,
            methods=["POST"],
            operation_id="nativeRecoveryAddressPrepareCurrent",
            response_model=NativeRecoveryAddressPreparedView,
            status_code=status.HTTP_202_ACCEPTED,
            responses={
                401: {"model": ErrorEnvelope},
                403: {"model": ErrorEnvelope},
                422: {"model": ErrorEnvelope},
                503: {"model": ErrorEnvelope},
            },
        )
        router.add_api_route(
            "/sessions/current/recovery-addresses",
            list_recovery_addresses,
            methods=["GET"],
            operation_id="nativeRecoveryAddressListCurrent",
            response_model=list[NativeRecoveryAddressView],
            responses={401: {"model": ErrorEnvelope}},
        )
        router.add_api_route(
            "/sessions/current/recovery-addresses/{recovery_address_id}",
            revoke_recovery_address,
            methods=["DELETE"],
            operation_id="nativeRecoveryAddressRevokeCurrent",
            status_code=status.HTTP_204_NO_CONTENT,
            response_model=None,
            responses={
                401: {"model": ErrorEnvelope},
                403: {"model": ErrorEnvelope},
                404: {"model": ErrorEnvelope},
            },
        )
        router.add_api_route(
            "/recovery-addresses:verify",
            verify_recovery_address,
            methods=["POST"],
            operation_id="nativeRecoveryAddressVerify",
            status_code=status.HTTP_204_NO_CONTENT,
            response_model=None,
            responses={401: {"model": ErrorEnvelope}},
        )
        router.add_api_route(
            "/password:request-recovery",
            request_verified_channel_recovery,
            methods=["POST"],
            operation_id="nativePasswordRecoveryRequest",
            status_code=status.HTTP_202_ACCEPTED,
            response_model=None,
            summary="Request account recovery through a pre-verified address",
            description=(
                "Always returns the same result. The request never reveals whether the "
                "login handle exists, has a verified recovery address, or whether delivery "
                "was possible."
            ),
        )
    if webauthn_login is not None:
        _register_webauthn_routes(
            router,
            registration_options=webauthn_registration_options,
            register_current_identity=webauthn_register_current_identity,
            authentication_options=webauthn_authentication_options,
            create_session=webauthn_create_session,
            step_up_options=webauthn_step_up_options,
            step_up=webauthn_step_up,
        )
    return router


def _register_webauthn_routes(
    router: APIRouter,
    *,
    registration_options: Any,
    register_current_identity: Any,
    authentication_options: Any,
    create_session: Any,
    step_up_options: Any,
    step_up: Any,
) -> None:
    router.add_api_route(
        "/sessions/current/webauthn/registration-options",
        registration_options,
        methods=["POST"],
        operation_id="nativeWebAuthnCurrentRegistrationOptions",
        response_model=NativeWebAuthnOptionsView,
        status_code=status.HTTP_200_OK,
        summary="Begin passkey registration for the current native identity",
        description=(
            "The bearer session determines the identity. The client cannot select another "
            "identity, and the one-time challenge is bound to that identity."
        ),
        responses={
            401: {"model": ErrorEnvelope, "description": "Session is invalid"},
        },
    )
    router.add_api_route(
        "/sessions/current/webauthn/registrations",
        register_current_identity,
        methods=["POST"],
        operation_id="nativeWebAuthnCurrentRegistrationComplete",
        response_model=NativeWebAuthnRegistrationView,
        status_code=status.HTTP_201_CREATED,
        summary="Verify and store a passkey for the current native identity",
        responses={
            401: {"model": ErrorEnvelope, "description": "Session or ceremony is invalid"},
            422: {"model": ErrorEnvelope, "description": "Invalid WebAuthn input"},
        },
    )
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


def _require_recent_phishing_resistant_subject(subject: AuthenticatedSubject) -> None:
    assurance = subject.metadata.get("authentication_assurance")
    user_verified = subject.metadata.get("user_verified") == "true"
    recovery_derived = subject.metadata.get("recovery_derived") == "true"
    if (
        recovery_derived
        or assurance != AuthenticationAssurance.PHISHING_RESISTANT.value
        or not user_verified
    ):
        raise PhishingResistantAuthenticationRequired(
            "recent phishing-resistant authentication is required"
        )
    raw_authenticated_at = subject.metadata.get("authenticated_at")
    if raw_authenticated_at is None:
        raise RecentAuthenticationRequired("recent strong authentication is required")
    try:
        authenticated_at = datetime.fromisoformat(raw_authenticated_at)
    except ValueError as exc:
        raise RecentAuthenticationRequired("recent strong authentication is required") from exc
    if authenticated_at.tzinfo is None:
        raise RecentAuthenticationRequired("recent strong authentication is required")
    if datetime.now(UTC) - authenticated_at > REAUTHENTICATION_WINDOW:
        raise RecentAuthenticationRequired("recent strong authentication is required")


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
