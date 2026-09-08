from fastapi import Request, status
from fastapi.responses import JSONResponse

from request_engine.entrypoints.http.errors import render_error_response
from request_engine.platform.http.errors import ErrorBody, ErrorResolution
from request_engine.platform.security.identity_resolution import (
    IdentityBindingPending,
    IdentityBindingRevoked,
    IdentityBindingSuspended,
    IdentityNotBound,
    IdentitySubjectClassMismatch,
    PrincipalProvisioningRequired,
    TenantContextAmbiguous,
    TenantContextRequired,
)
from request_engine.platform.security.native_auth import NativeAuthenticationError
from request_engine.platform.security.native_http import TenantContextInvalid


async def native_authentication_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, NativeAuthenticationError):
        raise exc
    return render_error_response(
        status.HTTP_401_UNAUTHORIZED,
        ErrorBody(
            code="credential_invalid",
            message="the native authentication credential is invalid or no longer usable",
            resolution=ErrorResolution.REAUTHENTICATE,
            retryable=False,
        ),
        headers={"WWW-Authenticate": "Bearer"},
    )


async def tenant_context_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, (TenantContextRequired, TenantContextInvalid)):
        raise exc
    code = (
        "tenant_context_required"
        if isinstance(exc, TenantContextRequired)
        else "tenant_context_invalid"
    )
    return render_error_response(
        status.HTTP_400_BAD_REQUEST,
        ErrorBody(
            code=code,
            message=str(exc),
            resolution=ErrorResolution.FIX_REQUEST,
            retryable=False,
        ),
    )


async def identity_resolution_error_handler(_: Request, exc: Exception) -> JSONResponse:
    mapping: tuple[tuple[type[Exception], str], ...] = (
        (IdentityNotBound, "identity_not_bound"),
        (IdentityBindingPending, "identity_binding_pending"),
        (IdentityBindingSuspended, "identity_binding_suspended"),
        (IdentityBindingRevoked, "identity_binding_revoked"),
        (TenantContextAmbiguous, "tenant_context_ambiguous"),
        (PrincipalProvisioningRequired, "principal_provisioning_required"),
        (IdentitySubjectClassMismatch, "identity_subject_class_mismatch"),
    )
    for error_type, code in mapping:
        if isinstance(exc, error_type):
            return render_error_response(
                status.HTTP_403_FORBIDDEN,
                ErrorBody(
                    code=code,
                    message=str(exc),
                    resolution=ErrorResolution.REQUEST_AUTHORITY,
                    retryable=False,
                ),
            )
    raise exc
