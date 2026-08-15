from enum import StrEnum

from pydantic import BaseModel, Field


class ErrorResolution(StrEnum):
    """Machine-readable next action for API/agent callers."""

    NONE = "none"
    RETRY_SAME_REQUEST = "retry_same_request"
    REFRESH_AND_RETRY = "refresh_and_retry"
    CHOOSE_ALTERNATIVE = "choose_alternative"
    FIX_REQUEST = "fix_request"
    REAUTHENTICATE = "reauthenticate"
    REQUEST_AUTHORITY = "request_authority"
    OPERATOR_INTERVENTION = "operator_intervention"


class ErrorBody(BaseModel):
    code: str
    message: str
    retryable: bool = False
    resolution: ErrorResolution = ErrorResolution.NONE
    details: dict[str, object] = Field(default_factory=dict)


class ErrorEnvelope(BaseModel):
    error: ErrorBody
