from uuid import UUID

from request_engine.modules.requests.domain.errors import RequestError
from request_engine.modules.requests.domain.errors import (
    RequestPayloadInvalid as RequestPayloadInvalid,
)
from request_engine.modules.requests.domain.errors import (
    UnsupportedRequestSchema as UnsupportedRequestSchema,
)


class RequestDefinitionNotFound(RequestError):
    def __init__(self, request_key: str, version: int | None) -> None:
        version_label = f" version {version}" if version is not None else ""
        super().__init__(f"RequestDefinition {request_key!r}{version_label} was not found")
        self.request_key = request_key
        self.version = version


class RequestDefinitionVersionNotFound(RequestError):
    def __init__(self, version_id: UUID) -> None:
        super().__init__(f"RequestDefinitionVersion {version_id} was not found")
        self.version_id = version_id


class RequestDefinitionInactive(RequestError):
    def __init__(self, version_id: UUID) -> None:
        super().__init__(f"RequestDefinitionVersion {version_id} belongs to an inactive definition")
        self.version_id = version_id


class RequestResultNotDefined(RequestError):
    def __init__(self, version_id: UUID) -> None:
        super().__init__(f"RequestDefinitionVersion {version_id} has no result schema")
        self.version_id = version_id


class RequestNotFound(RequestError):
    def __init__(self, request_id: UUID) -> None:
        super().__init__(f"Request {request_id} was not found")
        self.request_id = request_id


class RequestNotOpen(RequestError):
    def __init__(self, request_id: UUID, status: str) -> None:
        super().__init__(f"Request {request_id} is not open: {status}")
        self.request_id = request_id
        self.status = status


class RequestRevisionConflict(RequestError):
    def __init__(self, request_id: UUID, expected: int, actual: int) -> None:
        super().__init__(
            f"Request {request_id} revision mismatch: expected {expected}, current {actual}"
        )
        self.request_id = request_id
        self.expected = expected
        self.actual = actual


class RequestResultAlreadyRecorded(RequestError):
    def __init__(self, request_id: UUID) -> None:
        super().__init__(f"Request {request_id} already has a recorded result")
        self.request_id = request_id


class RequestResultRequired(RequestError):
    def __init__(self, request_id: UUID) -> None:
        super().__init__(f"Request {request_id} requires a validated result before completion")
        self.request_id = request_id


class RequestPartyNotUsable(RequestError):
    def __init__(self, party_id: UUID) -> None:
        super().__init__(f"Party {party_id} was not found or is inactive")
        self.party_id = party_id


class RequestPartyAuthorityRequired(RequestError):
    def __init__(self, requester_party_id: UUID | None, scope_key: str) -> None:
        requester = str(requester_party_id) if requester_party_id is not None else "unattributed Request"
        super().__init__(f"Party authority {scope_key!r} is required for {requester}")
        self.requester_party_id = requester_party_id
        self.scope_key = scope_key


class ExternalCorrelationConflict(RequestError):
    def __init__(self, correlation_kind: str, provider_key: str, external_key: str) -> None:
        super().__init__(
            "external correlation already belongs to another Request: "
            f"{correlation_kind}/{provider_key}/{external_key}"
        )
        self.correlation_kind = correlation_kind
        self.provider_key = provider_key
        self.external_key = external_key
