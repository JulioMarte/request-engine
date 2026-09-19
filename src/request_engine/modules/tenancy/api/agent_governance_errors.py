from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from request_engine.modules.tenancy.application.errors import (
    AgentGovernanceConflict,
    AgentGovernanceError,
    AgentGovernanceForbidden,
    AgentGovernanceInputInvalid,
    AgentGovernanceNotFound,
    AgentGovernanceRevisionConflict,
)
from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope, ErrorResolution


def add_agent_governance_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AgentGovernanceError, agent_governance_error_handler)


async def agent_governance_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, AgentGovernanceError):
        raise exc
    status_code, body = _agent_governance_error(exc)
    return JSONResponse(
        status_code=status_code,
        content=ErrorEnvelope(error=body).model_dump(mode="json"),
    )


def _agent_governance_error(exc: AgentGovernanceError) -> tuple[int, ErrorBody]:
    if isinstance(exc, AgentGovernanceForbidden):
        return status.HTTP_403_FORBIDDEN, ErrorBody(
            code="agent_governance_forbidden",
            message="the current actor may not perform this agent governance operation",
            resolution=ErrorResolution.REQUEST_AUTHORITY,
        )
    if isinstance(exc, AgentGovernanceNotFound):
        return status.HTTP_404_NOT_FOUND, ErrorBody(
            code="agent_governance_not_found",
            message="agent profile was not found in the current tenant",
            resolution=ErrorResolution.FIX_REQUEST,
        )
    if isinstance(exc, AgentGovernanceRevisionConflict):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="agent_governance_revision_conflict",
            message="agent state changed since the supplied revision",
            retryable=True,
            resolution=ErrorResolution.REFRESH_AND_RETRY,
        )
    if isinstance(exc, AgentGovernanceConflict):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="agent_governance_conflict",
            message="the requested agent governance change conflicts with current state",
            resolution=ErrorResolution.FIX_REQUEST,
        )
    if isinstance(exc, AgentGovernanceInputInvalid):
        return status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorBody(
            code="agent_governance_input_invalid",
            message="the requested agent governance input is invalid",
            resolution=ErrorResolution.FIX_REQUEST,
        )
    return status.HTTP_500_INTERNAL_SERVER_ERROR, ErrorBody(
        code="agent_governance_error",
        message="the agent governance command failed",
        resolution=ErrorResolution.OPERATOR_INTERVENTION,
    )
