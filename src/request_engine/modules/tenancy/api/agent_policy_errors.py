from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from request_engine.modules.tenancy.application.errors import (
    AgentPolicyError,
    AgentPolicyForbidden,
    AgentPolicyInputInvalid,
    AgentPolicyNotFound,
)
from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope, ErrorResolution


def add_agent_policy_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AgentPolicyError, agent_policy_error_handler)


async def agent_policy_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, AgentPolicyError):
        raise exc
    status_code, body = _agent_policy_error(exc)
    return JSONResponse(
        status_code=status_code,
        content=ErrorEnvelope(error=body).model_dump(mode="json"),
    )


def _agent_policy_error(exc: AgentPolicyError) -> tuple[int, ErrorBody]:
    if isinstance(exc, AgentPolicyForbidden):
        return status.HTTP_403_FORBIDDEN, ErrorBody(
            code="agent_policy_forbidden",
            message="the current actor may not perform this agent policy operation",
            resolution=ErrorResolution.REQUEST_AUTHORITY,
        )
    if isinstance(exc, AgentPolicyNotFound):
        return status.HTTP_404_NOT_FOUND, ErrorBody(
            code="agent_policy_not_found",
            message="agent policy was not found in the current tenant",
            resolution=ErrorResolution.FIX_REQUEST,
        )
    if isinstance(exc, AgentPolicyInputInvalid):
        return status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorBody(
            code="agent_policy_input_invalid",
            message="the requested agent policy input is invalid",
            resolution=ErrorResolution.FIX_REQUEST,
        )
    return status.HTTP_500_INTERNAL_SERVER_ERROR, ErrorBody(
        code="agent_policy_error",
        message="the agent policy command failed",
        resolution=ErrorResolution.OPERATOR_INTERVENTION,
    )
