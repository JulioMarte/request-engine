"""Global error-handler registration for the process entrypoint."""

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from request_engine.entrypoints.http.errors import (
    authentication_required_handler,
    capability_required_handler,
    http_exception_handler,
    idempotency_conflict_handler,
    integrity_error_handler,
    render_error_response,
    request_validation_error_handler,
)
from request_engine.entrypoints.http.native_auth_errors import (
    delegation_resolution_error_handler,
    identity_resolution_error_handler,
    native_authentication_error_handler,
    tenant_context_error_handler,
    workload_authentication_error_handler,
)
from request_engine.entrypoints.http.operational_errors import (
    operational_authority_required_handler,
)
from request_engine.platform.http.errors import ErrorBody, ErrorResolution
from request_engine.platform.idempotency.errors import IdempotencyConflict
from request_engine.platform.security.acting_operator import (
    AgentActingOperatorRelayForbidden,
    OperatorResolutionUnavailable,
)
from request_engine.platform.security.agent_policy import (
    AgentBudgetExceeded,
    AgentPolicyDenied,
    AgentRiskDenied,
)
from request_engine.platform.security.delegation import DelegationResolutionError
from request_engine.platform.security.http import AuthenticationRequired, CapabilityRequired
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
from request_engine.platform.security.operational_authority import OperationalAuthorityRequired
from request_engine.platform.security.workload_auth import WorkloadAuthenticationError


async def operator_resolution_unavailable_handler(_: Request, exc: Exception) -> JSONResponse:
    return render_error_response(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        ErrorBody(
            code="operator_resolution_unavailable",
            message="the deployment does not provide acting-operator resolution",
            resolution=ErrorResolution.RETRY_SAME_REQUEST,
            retryable=True,
        ),
    )


async def agent_acting_operator_relay_forbidden_handler(_: Request, exc: Exception) -> JSONResponse:
    return render_error_response(
        status.HTTP_403_FORBIDDEN,
        ErrorBody(
            code="agent_delegation_required",
            message="agents must use standing authority or an explicit bounded delegation",
            resolution=ErrorResolution.REQUEST_AUTHORITY,
            retryable=False,
        ),
    )


async def agent_policy_denied_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, AgentPolicyDenied):
        raise exc
    return render_error_response(
        status.HTTP_403_FORBIDDEN,
        ErrorBody(
            code="agent_policy_denied",
            message=str(exc),
            resolution=ErrorResolution.REQUEST_AUTHORITY,
            retryable=False,
        ),
    )


async def agent_risk_denied_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, AgentRiskDenied):
        raise exc
    return render_error_response(
        status.HTTP_403_FORBIDDEN,
        ErrorBody(
            code="agent_risk_denied",
            message=str(exc),
            resolution=ErrorResolution.REQUEST_AUTHORITY,
            retryable=False,
        ),
    )


async def agent_budget_exceeded_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, AgentBudgetExceeded):
        raise exc
    return render_error_response(
        status.HTTP_429_TOO_MANY_REQUESTS,
        ErrorBody(
            code="agent_budget_exceeded",
            message=str(exc),
            resolution=ErrorResolution.RETRY_SAME_REQUEST,
            retryable=True,
        ),
    )


def add_global_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AuthenticationRequired, authentication_required_handler)
    app.add_exception_handler(NativeAuthenticationError, native_authentication_error_handler)
    app.add_exception_handler(WorkloadAuthenticationError, workload_authentication_error_handler)
    app.add_exception_handler(DelegationResolutionError, delegation_resolution_error_handler)
    app.add_exception_handler(TenantContextRequired, tenant_context_error_handler)
    app.add_exception_handler(TenantContextInvalid, tenant_context_error_handler)
    for error_type in (
        IdentityNotBound,
        IdentityBindingPending,
        IdentityBindingSuspended,
        IdentityBindingRevoked,
        TenantContextAmbiguous,
        PrincipalProvisioningRequired,
        IdentitySubjectClassMismatch,
    ):
        app.add_exception_handler(error_type, identity_resolution_error_handler)
    app.add_exception_handler(CapabilityRequired, capability_required_handler)
    app.add_exception_handler(OperationalAuthorityRequired, operational_authority_required_handler)
    app.add_exception_handler(
        OperatorResolutionUnavailable, operator_resolution_unavailable_handler
    )
    app.add_exception_handler(
        AgentActingOperatorRelayForbidden, agent_acting_operator_relay_forbidden_handler
    )
    app.add_exception_handler(AgentPolicyDenied, agent_policy_denied_handler)
    app.add_exception_handler(AgentRiskDenied, agent_risk_denied_handler)
    app.add_exception_handler(AgentBudgetExceeded, agent_budget_exceeded_handler)
    app.add_exception_handler(IdempotencyConflict, idempotency_conflict_handler)
    app.add_exception_handler(RequestValidationError, request_validation_error_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(IntegrityError, integrity_error_handler)
