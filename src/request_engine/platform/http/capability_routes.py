from collections.abc import Callable
from typing import Any

from fastapi import APIRouter

from request_engine.platform.security.capabilities import (
    CapabilityExposure,
    capability_definition,
)


def add_capability_route(
    router: APIRouter,
    path: str,
    endpoint: Callable[..., Any],
    *,
    capability: str,
    methods: list[str],
    operation_id: str | None = None,
    **kwargs: Any,
) -> None:
    """Register one HTTP operation from its canonical capability definition."""

    definition = capability_definition(capability)
    if definition is None:
        raise ValueError(f"unknown capability {capability!r}")
    if not definition.runtime_available:
        raise ValueError(f"capability {capability!r} is not runtime-invocable")

    extra = dict(kwargs.pop("openapi_extra", {}) or {})
    extra.update(
        {
            "x-request-engine-capability": definition.key,
            "x-request-engine-schema-version": definition.schema_version,
            "x-request-engine-idempotency": definition.idempotency.value,
            "x-request-engine-expected-revision": definition.revision.value,
            "x-request-engine-exposure": definition.exposure.value,
        }
    )
    if definition.party_scope is not None:
        extra["x-request-engine-party-scope"] = definition.party_scope
    if definition.override_capability is not None:
        extra["x-request-engine-override-capability"] = definition.override_capability

    router.add_api_route(
        path,
        endpoint,
        methods=methods,
        operation_id=operation_id or definition.key.replace(".", "_"),
        include_in_schema=definition.exposure is not CapabilityExposure.INTERNAL,
        openapi_extra=extra,
        **kwargs,
    )
