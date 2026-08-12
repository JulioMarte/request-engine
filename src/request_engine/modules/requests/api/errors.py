from fastapi import Request, status
from fastapi.responses import JSONResponse

from request_engine.modules.requests.application.errors import (
    ExternalCorrelationConflict,
    RequestDefinitionInactive,
    RequestDefinitionNotFound,
    RequestDefinitionVersionNotFound,
    RequestError,
    RequestNotFound,
    RequestNotOpen,
    RequestPartyAuthorityRequired,
    RequestPartyNotUsable,
    RequestPayloadInvalid,
    RequestResultAlreadyRecorded,
    RequestResultNotDefined,
    RequestResultRequired,
    RequestRevisionConflict,
    UnsupportedRequestSchema,
)
from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope


async def request_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestError):
        raise exc
    status_code, body = _request_error(exc)
    return JSONResponse(status_code=status_code, content=ErrorEnvelope(error=body).model_dump())


def _request_error(exc: RequestError) -> tuple[int, ErrorBody]:
    if isinstance(exc, RequestDefinitionNotFound):
        return status.HTTP_404_NOT_FOUND, ErrorBody(
            code="request_definition_not_found",
            message=str(exc),
            details={"request_key": exc.request_key, "version": exc.version},
        )
    if isinstance(exc, RequestDefinitionVersionNotFound):
        return status.HTTP_404_NOT_FOUND, ErrorBody(
            code="request_definition_version_not_found",
            message=str(exc),
            details={"version_id": str(exc.version_id)},
        )
    if isinstance(exc, RequestNotFound):
        return status.HTTP_404_NOT_FOUND, ErrorBody(
            code="request_not_found",
            message=str(exc),
            details={"request_id": str(exc.request_id)},
        )
    if isinstance(exc, RequestPartyAuthorityRequired):
        return status.HTTP_403_FORBIDDEN, ErrorBody(
            code="request_party_authority_required",
            message=str(exc),
            details={
                "requester_party_id": (
                    str(exc.requester_party_id) if exc.requester_party_id is not None else None
                ),
                "scope_key": exc.scope_key,
            },
        )
    if isinstance(exc, RequestPayloadInvalid):
        return status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorBody(
            code="request_payload_invalid",
            message=str(exc),
            details={"path": exc.path, "reason": exc.reason},
        )
    if isinstance(exc, RequestPartyNotUsable):
        return status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorBody(
            code="request_party_not_usable",
            message=str(exc),
            details={"party_id": str(exc.party_id)},
        )
    if isinstance(exc, UnsupportedRequestSchema):
        return status.HTTP_500_INTERNAL_SERVER_ERROR, ErrorBody(
            code="request_definition_invalid",
            message="the configured Request definition uses an unsupported schema",
            details={"path": exc.path, "keyword": exc.keyword},
        )
    if isinstance(exc, RequestRevisionConflict):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="revision_conflict",
            message="the aggregate changed since it was read",
            details={
                "aggregate_kind": "Request",
                "aggregate_id": str(exc.request_id),
                "expected_revision": exc.expected,
                "current_revision": exc.actual,
            },
        )
    if isinstance(exc, RequestNotOpen):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="request_not_open",
            message=str(exc),
            details={"request_id": str(exc.request_id), "status": exc.status},
        )
    if isinstance(exc, ExternalCorrelationConflict):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="external_correlation_conflict",
            message=str(exc),
            details={
                "correlation_kind": exc.correlation_kind,
                "provider_key": exc.provider_key,
                "external_key": exc.external_key,
            },
        )
    if isinstance(exc, RequestResultAlreadyRecorded):
        return _conflict("request_result_already_recorded", exc)
    if isinstance(exc, RequestResultRequired):
        return _conflict("request_result_required", exc)
    if isinstance(exc, RequestResultNotDefined):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="request_result_not_defined",
            message=str(exc),
            details={"version_id": str(exc.version_id)},
        )
    if isinstance(exc, RequestDefinitionInactive):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="request_definition_inactive",
            message=str(exc),
            details={"version_id": str(exc.version_id)},
        )
    return status.HTTP_500_INTERNAL_SERVER_ERROR, ErrorBody(
        code="request_error",
        message="the Request command failed",
    )


def _conflict(
    code: str,
    exc: RequestResultAlreadyRecorded | RequestResultRequired,
) -> tuple[int, ErrorBody]:
    return status.HTTP_409_CONFLICT, ErrorBody(
        code=code,
        message=str(exc),
        details={"request_id": str(exc.request_id)},
    )
