from fastapi import Request, status
from fastapi.responses import JSONResponse

from request_engine.modules.discovery.application.errors import (
    DiscoverySearchContractError,
    DiscoverySearchTooBroad,
)
from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope, ErrorResolution


async def discovery_search_error_handler(
    _: Request,
    exc: Exception,
) -> JSONResponse:
    if not isinstance(exc, DiscoverySearchContractError):
        raise exc
    code = "discovery_search_too_broad" if isinstance(exc, DiscoverySearchTooBroad) else "invalid_discovery_search"
    body = ErrorBody(
        code=code,
        message=str(exc),
        resolution=ErrorResolution.REFRESH_AND_RETRY,
        details={},
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=ErrorEnvelope(error=body).model_dump(mode="json"),
    )
