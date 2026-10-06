from enum import StrEnum
from typing import Any, cast

from fastapi import FastAPI
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


def install_validation_error_schema(app: FastAPI) -> None:
    """Project transport validation and the last-resort technical failure contract.

    Replace only the framework default, not an owner's explicitly declared response.
    Register before first OpenAPI generation; route registration remains owner-local.
    """
    original_openapi = app.openapi

    def error_openapi() -> dict[str, Any]:
        schema = original_openapi()
        envelope = ErrorEnvelope.model_json_schema(ref_template="#/components/schemas/{model}")
        models = schema.setdefault("components", {}).setdefault("schemas", {})
        models.update(envelope.pop("$defs", {}))
        models.setdefault("ErrorEnvelope", envelope)
        for path in schema.get("paths", {}).values():
            for operation in path.values():
                if not isinstance(operation, dict) or "operationId" not in operation:
                    continue
                operation = cast(dict[str, Any], operation)
                responses = operation.setdefault("responses", {})
                if getattr(app.state, "http_request_budget_installed", False):
                    for status, description in (
                        ("400", "Invalid transport Content-Length; fix_request, retryable=false."),
                        ("408", "Body reading exceeded its deadline before owner execution."),
                        ("413", "Actual body exceeds the transport limit before owner execution."),
                        ("503", "Capacity unavailable; retry_same_request with bounded backoff."),
                    ):
                        headers: dict[str, Any] = {
                            "X-Correlation-ID": {"schema": {"type": "string", "format": "uuid"}},
                            "Cache-Control": {"schema": {"type": "string"}},
                        }
                        if status == "503":
                            headers["Retry-After"] = {"schema": {"type": "string"}}
                        responses.setdefault(
                            status,
                            {
                                "description": description,
                                "headers": headers,
                                "content": {
                                    "application/json": {
                                        "schema": {"$ref": "#/components/schemas/ErrorEnvelope"}
                                    }
                                },
                            },
                        )
                responses.setdefault(
                    "500",
                    {
                        "description": (
                            "Unexpected server failure: internal_error, operator_intervention, "
                            "retryable=false. The operation outcome may be uncertain; "
                            "this response does not prove rollback."
                        ),
                        "headers": {
                            "X-Correlation-ID": {"schema": {"type": "string", "format": "uuid"}},
                            "Cache-Control": {"schema": {"type": "string"}},
                        },
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/ErrorEnvelope"}
                            }
                        },
                    },
                )
                response = responses.get("422", {})
                content = response.get("content", {}).get("application/json", {})
                if content.get("schema") == {"$ref": "#/components/schemas/HTTPValidationError"}:
                    content["schema"] = {"$ref": "#/components/schemas/ErrorEnvelope"}
                    response["description"] = (
                        "Input validation failed; error.details.fields identifies invalid fields"
                    )
        return schema

    app.openapi = error_openapi
