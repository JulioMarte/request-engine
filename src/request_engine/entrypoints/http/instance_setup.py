"""First-run Instance setup and atomic claim HTTP surface (ADR 0014 §6-§9).

This router is the only installation ceremony surface. While the Instance is
UNCLAIMED no Principal exists, so these routes deliberately use a dedicated
``Authorization: Setup <opaque-token>`` resolver instead of the ordinary
``PlatformActorResolver``. They never accept tenant/actor headers or
caller-selected Principal/capability claims, and they are never projected as
agent/MCP tools.

Recovery codes are one-time secrets: they are returned once and never replayed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from request_engine.entrypoints.http.errors import render_error_response
from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope, ErrorResolution
from request_engine.platform.security.instance_setup import (
    InstanceClaimResult,
    InstanceSetupService,
    SetupSessionUnusable,
    SetupStepInvalid,
)
from request_engine.platform.security.native_auth import normalize_login_handle
from request_engine.platform.security.native_webauthn_auth import WebAuthnCeremonyError
from request_engine.platform.security.webauthn import WebAuthnInputError, public_key_to_json

_SETUP_SCHEME = "setup"


class SetupAuthenticationRequired(Exception):
    """The request did not present a well-formed SetupSession bearer."""


class SetupDiscoveryView(BaseModel):
    setup_required: bool


class SetupSessionView(BaseModel):
    setup_session_id: UUID
    token: str = Field(repr=False)
    expires_at: datetime


class SetupNativeIdentityBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    login_handle: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=1024, repr=False)

    @field_validator("login_handle")
    @classmethod
    def validate_handle(cls, value: str) -> str:
        return normalize_login_handle(value)


class SetupWebAuthnRegistrationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credential: dict[str, Any]


class SetupFinalizeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_provenance: str = Field(min_length=1, max_length=500)


class SetupWebAuthnOptionsView(BaseModel):
    public_key: dict[str, Any]


class SetupRecoveryCodesView(BaseModel):
    codes: list[str]


class InstanceClaimView(BaseModel):
    instance_id: UUID
    owner_principal_id: UUID
    native_identity_id: UUID
    policy_key: str
    built_in_native_authority_id: UUID
    built_in_workload_authority_id: UUID


def install_instance_setup_http(app: Any, *, service: InstanceSetupService) -> None:
    """Install the setup/claim ceremony routes on the private control plane."""

    router = APIRouter(prefix="/v1/setup", tags=["Instance setup"])

    async def discovery() -> SetupDiscoveryView | JSONResponse:
        instance = await service.read_instance()
        if instance is None:
            return _error(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "instance_not_initialized",
                "the platform instance is not initialized",
                ErrorResolution.OPERATOR_INTERVENTION,
            )
        return SetupDiscoveryView(setup_required=instance.state == "unclaimed")

    async def create_session(response: Response) -> SetupSessionView | JSONResponse:
        try:
            issued = await service.create_setup_session()
        except SetupSessionUnusable:
            return _setup_closed()
        _prevent_secret_caching(response)
        return SetupSessionView(
            setup_session_id=issued.setup_session_id,
            token=issued.raw_token,
            expires_at=issued.expires_at,
        )

    async def set_native_identity(
        request: Request, payload: SetupNativeIdentityBody
    ) -> Response | JSONResponse:
        snapshot = await _resolve(service, request)
        try:
            await service.set_pending_identity(
                setup_session_id=snapshot,
                login_handle=payload.login_handle,
                password=payload.password,
            )
        except SetupStepInvalid:
            return _step_invalid()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    async def webauthn_registration_options(
        request: Request, response: Response
    ) -> SetupWebAuthnOptionsView | JSONResponse:
        snapshot = await _resolve(service, request)
        try:
            started = await service.begin_webauthn_registration(setup_session_id=snapshot)
        except (WebAuthnCeremonyError, WebAuthnInputError):
            return _step_invalid()
        _prevent_secret_caching(response)
        return SetupWebAuthnOptionsView(public_key=public_key_to_json(dict(started.public_key)))

    async def webauthn_register(
        request: Request, payload: SetupWebAuthnRegistrationBody
    ) -> Response | JSONResponse:
        snapshot = await _resolve(service, request)
        try:
            await service.complete_webauthn_registration(
                setup_session_id=snapshot, credential=payload.credential
            )
        except (WebAuthnCeremonyError, WebAuthnInputError):
            return _step_invalid()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    async def issue_recovery_codes(
        request: Request, response: Response
    ) -> SetupRecoveryCodesView | JSONResponse:
        snapshot = await _resolve(service, request)
        try:
            codes = await service.issue_recovery_codes(setup_session_id=snapshot)
        except SetupStepInvalid:
            return _step_invalid()
        _prevent_secret_caching(response)
        return SetupRecoveryCodesView(codes=list(codes))

    async def finalize(
        request: Request, payload: SetupFinalizeBody
    ) -> InstanceClaimView | JSONResponse:
        idempotency_key = _idempotency_key(request)
        if idempotency_key is None:
            return _error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "idempotency_key_required",
                "an Idempotency-Key header is required to finalize the instance claim",
                ErrorResolution.FIX_REQUEST,
            )
        raw_token = _setup_token(request)
        session = await service.resolve_setup_session(raw_token=raw_token)
        if session.status == "consumed":
            # Exact-replay path: the winning finalize already committed. The
            # receipt is returned only when the request fingerprint matches; a
            # reused key with different content is a conflict, never a foreign
            # receipt. Setup authority is never reactivated.
            receipt = await service.lookup_claim(
                setup_session_id=session.setup_session_id,
                idempotency_key=idempotency_key,
                claim_provenance=payload.claim_provenance,
            )
            if receipt is None:
                # The key exists but for a different request fingerprint: a
                # machine-readable idempotency conflict, not a generic closed
                # setup. A key that was never used is a new claim against a
                # closed instance.
                if await service.is_claim_conflict(
                    setup_session_id=session.setup_session_id,
                    idempotency_key=idempotency_key,
                    claim_provenance=payload.claim_provenance,
                ):
                    return _idempotency_conflict()
                return _setup_closed()
            return await _claim_view(service, receipt)
        if not session.is_usable:
            return _setup_closed()
        try:
            result = await service.finalize(
                setup_session_id=session.setup_session_id,
                idempotency_key=idempotency_key,
                claim_provenance=payload.claim_provenance,
            )
        except SetupStepInvalid:
            return _setup_closed()
        return await _claim_view(service, result)

    router.add_api_route(
        "",
        discovery,
        methods=["GET"],
        operation_id="instanceSetupDiscovery",
        response_model=SetupDiscoveryView,
        summary="Report whether first-run instance setup is still required",
        description=(
            "Anonymous installation discovery. Returns only whether the instance "
            "is still UNCLAIMED. It never leaks owner identity, counts or security "
            "configuration, and it is unavailable once the instance is claimed."
        ),
    )
    router.add_api_route(
        "/sessions",
        create_session,
        methods=["POST"],
        operation_id="instanceSetupSessionCreate",
        response_model=SetupSessionView,
        status_code=status.HTTP_201_CREATED,
        summary="Create a bounded one-time SetupSession bearer",
        description=(
            "Creates a bounded SetupSession and returns its opaque bearer once. "
            "The operation is deliberately not replay-idempotent because only a "
            "digest is persisted; create a new bounded session if the response is "
            "lost. It is closed permanently once the instance is claimed."
        ),
        responses={
            409: {"model": ErrorEnvelope, "description": "Setup is closed or bounded"},
        },
    )
    router.add_api_route(
        "/native-identity",
        set_native_identity,
        methods=["POST"],
        operation_id="instanceSetupNativeIdentitySet",
        response_model=None,
        status_code=status.HTTP_204_NO_CONTENT,
        summary="Record the pending Platform Owner native credential",
        responses={409: {"model": ErrorEnvelope, "description": "Setup session unusable"}},
    )
    router.add_api_route(
        "/webauthn/registration-options",
        webauthn_registration_options,
        methods=["POST"],
        operation_id="instanceSetupWebAuthnRegistrationOptions",
        response_model=SetupWebAuthnOptionsView,
        status_code=status.HTTP_200_OK,
        summary="Begin the setup WebAuthn registration ceremony",
        responses={409: {"model": ErrorEnvelope, "description": "Setup session unusable"}},
    )
    router.add_api_route(
        "/webauthn/registrations",
        webauthn_register,
        methods=["POST"],
        operation_id="instanceSetupWebAuthnRegistrationComplete",
        response_model=None,
        status_code=status.HTTP_204_NO_CONTENT,
        summary="Verify and store a setup WebAuthn registration",
        responses={409: {"model": ErrorEnvelope, "description": "Ceremony rejected"}},
    )
    router.add_api_route(
        "/recovery-codes",
        issue_recovery_codes,
        methods=["POST"],
        operation_id="instanceSetupRecoveryCodesIssue",
        response_model=SetupRecoveryCodesView,
        status_code=status.HTTP_201_CREATED,
        summary="Issue one-time Platform Owner recovery codes",
        description=(
            "Generates a fresh active recovery-code set and returns the plaintext "
            "codes exactly once. Only digests are persisted; a lost response "
            "requires regeneration, which atomically invalidates the prior set."
        ),
        responses={409: {"model": ErrorEnvelope, "description": "Setup session unusable"}},
    )
    router.add_api_route(
        "/recovery-codes:regenerate",
        issue_recovery_codes,
        methods=["POST"],
        operation_id="instanceSetupRecoveryCodesRegenerate",
        response_model=SetupRecoveryCodesView,
        status_code=status.HTTP_201_CREATED,
        summary="Regenerate Platform Owner recovery codes",
        responses={409: {"model": ErrorEnvelope, "description": "Setup session unusable"}},
    )
    router.add_api_route(
        ":finalize",
        finalize,
        methods=["POST"],
        operation_id="instanceSetupFinalize",
        response_model=InstanceClaimView,
        status_code=status.HTTP_201_CREATED,
        summary="Atomically claim the instance and create the Platform Owner",
        description=(
            "Requires a valid SetupSession bearer and an Idempotency-Key header. "
            "Atomically promotes the pending identity and passkey, grants the "
            "immutable platform-owner policy, promotes recovery codes, consumes "
            "the SetupSession and permanently closes setup. An exact replay with "
            "the same key and the same request fingerprint returns the same "
            "non-secret result; reusing the key with different content is a "
            "conflict and never redisplay recovery codes."
        ),
        responses={
            409: {"model": ErrorEnvelope, "description": "Setup session unusable"},
            422: {"model": ErrorEnvelope, "description": "Missing idempotency key"},
        },
    )
    app.include_router(router)
    app.add_exception_handler(SetupAuthenticationRequired, _setup_auth_handler)


async def _setup_auth_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, SetupAuthenticationRequired):
        raise exc
    return render_error_response(
        status.HTTP_401_UNAUTHORIZED,
        ErrorBody(
            code="setup_authentication_required",
            message="a valid SetupSession bearer is required",
            resolution=ErrorResolution.REAUTHENTICATE,
            retryable=False,
        ),
        headers={
            "WWW-Authenticate": "Setup",
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
        },
    )


async def _resolve(service: InstanceSetupService, request: Request) -> UUID:
    raw_token = _setup_token(request)
    session = await service.resolve_setup_session(raw_token=raw_token)
    if not session.is_usable:
        raise SetupSessionUnusable("setup session is not usable")
    return session.setup_session_id


def _setup_token(request: Request) -> str:
    header = request.headers.get("authorization")
    if header is None:
        raise SetupAuthenticationRequired("setup authorization is required")
    scheme, _, value = header.partition(" ")
    if scheme.strip().lower() != _SETUP_SCHEME or not value.strip():
        raise SetupAuthenticationRequired("setup authorization is malformed")
    return value.strip()


def _idempotency_key(request: Request) -> str | None:
    value = request.headers.get("idempotency-key")
    if value is None or not value.strip():
        return None
    return value.strip()


async def _claim_view(
    service: InstanceSetupService, result: InstanceClaimResult
) -> InstanceClaimView:
    instance = await service.read_instance()
    if instance is None:
        raise SetupStepInvalid("instance disappeared during claim")
    return InstanceClaimView(
        instance_id=result.instance_id,
        owner_principal_id=result.owner_principal_id,
        native_identity_id=result.native_identity_id,
        policy_key=result.policy_key,
        built_in_native_authority_id=instance.built_in_native_authority_id,
        built_in_workload_authority_id=instance.built_in_workload_authority_id,
    )


def _setup_closed() -> JSONResponse:
    return _error(
        status.HTTP_409_CONFLICT,
        "instance_setup_closed",
        "instance setup is closed or the setup session is no longer usable",
        ErrorResolution.OPERATOR_INTERVENTION,
    )


def _idempotency_conflict() -> JSONResponse:
    return _error(
        status.HTTP_409_CONFLICT,
        "idempotency_conflict",
        "the Idempotency-Key was already used for a different finalize request",
        ErrorResolution.FIX_REQUEST,
    )


def _step_invalid() -> JSONResponse:
    return _error(
        status.HTTP_409_CONFLICT,
        "instance_setup_step_invalid",
        "the requested setup step is not valid for the current setup state",
        ErrorResolution.FIX_REQUEST,
    )


def _error(
    status_code: int,
    code: str,
    message: str,
    resolution: ErrorResolution,
) -> JSONResponse:
    return render_error_response(
        status_code,
        ErrorBody(code=code, message=message, resolution=resolution, retryable=False),
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


def _prevent_secret_caching(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


__all__ = ["install_instance_setup_http", "SetupAuthenticationRequired"]
