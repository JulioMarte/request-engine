"""Describe composed HTTP authentication without implementing authorization."""

from typing import Any, cast

from fastapi import FastAPI

from request_engine.platform.http.errors import ErrorEnvelope
from request_engine.platform.security.tenant_http import ORGANIZATION_HEADER


def install_authentication_schema(
    app: FastAPI, *, scheme_name: str, description: str, tenant_context: bool = False
) -> None:
    """Project the deployment bearer boundary, never a second policy registry.

    Capability/discovery metadata identifies actor-authenticated operations.
    Native ceremony owners explicitly mark their session-bound operations.
    Existing owner security requirements are retained (e.g. proof-only routes).
    """
    original_openapi = app.openapi

    def authenticated_openapi() -> dict[str, Any]:
        schema = original_openapi()
        components = schema.setdefault("components", {})
        components.setdefault("securitySchemes", {})[scheme_name] = {
            "type": "http",
            "scheme": "bearer",
            "description": description,
        }
        components["securitySchemes"]["NativeSessionBearer"] = {
            "type": "http",
            "scheme": "bearer",
            "description": "An active native human session; never workload or federated evidence.",
        }
        envelope = ErrorEnvelope.model_json_schema(ref_template="#/components/schemas/{model}")
        components.setdefault("schemas", {}).update(envelope.pop("$defs", {}))
        components["schemas"].setdefault("ErrorEnvelope", envelope)
        for path in schema.get("paths", {}).values():
            for operation in path.values():
                if not isinstance(operation, dict) or "operationId" not in operation:
                    continue
                operation = cast(dict[str, Any], operation)
                session_bound = operation.get("x-request-engine-native-session") is True
                actor_bound = bool(operation.get("x-request-engine-capability")) or bool(
                    operation.get("x-request-engine-discovery")
                )
                subject_bound = operation.get("x-request-engine-authentication") == "human-subject"
                if not session_bound and not actor_bound and not subject_bound:
                    continue
                operation.setdefault(
                    "security", [{"NativeSessionBearer" if session_bound else scheme_name: []}]
                )
                responses = operation.setdefault("responses", {})
                responses.setdefault(
                    "401",
                    {
                        "description": "Authentication missing, invalid or no longer usable",
                        "headers": {"WWW-Authenticate": {"schema": {"type": "string"}}},
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/ErrorEnvelope"}
                            }
                        },
                    },
                )
                if actor_bound:
                    responses.setdefault(
                        "403",
                        {
                            "description": "Authenticated actor lacks required authority",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/ErrorEnvelope"}
                                }
                            },
                        },
                    )
                    if tenant_context:
                        operation["x-request-engine-tenant-context"] = (
                            f"{ORGANIZATION_HEADER} is required context, never authority. "
                            "Request Engine validates the subject's current binding and grants."
                        )
                        parameters = operation.setdefault("parameters", [])
                        if not any(
                            parameter.get("in") == "header"
                            and parameter.get("name", "").casefold()
                            == ORGANIZATION_HEADER.casefold()
                            for parameter in parameters
                        ):
                            parameters.append(
                                {
                                    "name": ORGANIZATION_HEADER,
                                    "in": "header",
                                    "required": True,
                                    "description": "Tenant selector, never authority",
                                    "schema": {"type": "string", "format": "uuid"},
                                }
                            )
        return schema

    app.openapi = authenticated_openapi


__all__ = ["install_authentication_schema"]
