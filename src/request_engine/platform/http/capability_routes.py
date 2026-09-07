import re
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter

from request_engine.platform.security.capabilities import (
    CapabilityExposure,
    capability_definition,
)

_TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_TOOL_AUDIENCES = frozenset({"public", "operator", "admin", "system"})
_MODULE_PREFIX = "request_engine.modules."


def _infer_owner(endpoint: Callable[..., Any]) -> str | None:
    module_name = getattr(endpoint, "__module__", "")
    if not module_name.startswith(_MODULE_PREFIX):
        return None
    remainder = module_name[len(_MODULE_PREFIX) :]
    owner, _, _ = remainder.partition(".")
    return owner or None


def add_capability_route(
    router: APIRouter,
    path: str,
    endpoint: Callable[..., Any],
    *,
    capability: str,
    methods: list[str],
    operation_id: str | None = None,
    owner: str | None = None,
    tool_name: str | None = None,
    tool_audiences: tuple[str, ...] = (),
    **kwargs: Any,
) -> None:
    """Register one HTTP operation from capability policy and operation metadata.

    Capability policy answers whether an actor may perform the operation. ``operation_id``
    identifies the HTTP/OpenAPI operation. Optional tool metadata declares that the same
    owner operation may later be projected to an authorized agent-tool surface; it never
    grants authority and does not introduce a second business execution path.
    """

    definition = capability_definition(capability)
    if definition is None:
        raise ValueError(f"unknown capability {capability!r}")
    if not definition.runtime_available:
        raise ValueError(f"capability {capability!r} is not runtime-invocable")

    resolved_operation_id = operation_id or definition.key.replace(".", "_")
    resolved_owner = owner or _infer_owner(endpoint)
    unknown_audiences = set(tool_audiences) - _TOOL_AUDIENCES
    if unknown_audiences:
        raise ValueError(f"unknown tool audiences: {sorted(unknown_audiences)}")
    if tool_name is not None and not tool_audiences:
        raise ValueError("tool_name requires at least one tool audience")
    if tool_audiences:
        if operation_id is None:
            raise ValueError("tool-exposed operations require an explicit stable operation_id")
        if resolved_owner is None:
            raise ValueError("tool-exposed operations require an explicit or inferable owner")
    resolved_tool_name = tool_name or (resolved_operation_id if tool_audiences else None)
    if resolved_tool_name is not None and _TOOL_NAME_RE.fullmatch(resolved_tool_name) is None:
        raise ValueError(
            "tool_name must be 1-128 characters using only letters, digits, '_', '-' or '.'"
        )

    extra = dict(kwargs.pop("openapi_extra", {}) or {})
    extra.update(
        {
            "x-request-engine-operation-id": resolved_operation_id,
            "x-request-engine-capability": definition.key,
            "x-request-engine-schema-version": definition.schema_version,
            "x-request-engine-kind": definition.kind.value,
            "x-request-engine-idempotency": definition.idempotency.value,
            "x-request-engine-expected-revision": definition.revision.value,
            "x-request-engine-exposure": definition.exposure.value,
        }
    )
    if resolved_owner is not None:
        extra["x-request-engine-owner"] = resolved_owner
    if resolved_tool_name is not None:
        extra["x-request-engine-tool-name"] = resolved_tool_name
        extra["x-request-engine-tool-audiences"] = list(dict.fromkeys(tool_audiences))
    if definition.party_scope is not None:
        extra["x-request-engine-party-scope"] = definition.party_scope
    if definition.override_capability is not None:
        extra["x-request-engine-override-capability"] = definition.override_capability

    router.add_api_route(
        path,
        endpoint,
        methods=methods,
        operation_id=resolved_operation_id,
        include_in_schema=definition.exposure is not CapabilityExposure.INTERNAL,
        openapi_extra=extra,
        **kwargs,
    )
