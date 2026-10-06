"""Presentation-only classification for the operator console.

The registry answers where an OpenAPI operation is discoverable in the console.
It deliberately carries no capability, authorization, revision or idempotency
policy: those remain canonical on :class:`AdminOperation`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from request_engine.entrypoints.http.admin_console.catalog import AdminCatalog, AdminOperation
from request_engine.entrypoints.http.admin_console.resources import (
    CONFIGURATION_OPERATION_IDS,
    DEPLOYMENT_OPERATION_IDS,
    OWNER_OPERATION_IDS,
    PROVISIONING_OPERATION_IDS,
    RESOURCE_SPECS,
    SECRET_OPERATION_IDS,
)

Experience = Literal["journey", "workspace", "advanced"]


@dataclass(frozen=True)
class SurfaceCoverage:
    operation_id: str
    experience: Experience
    destination: str


def _workspace_operations() -> dict[str, str]:
    covered: dict[str, str] = {}
    for spec in RESOURCE_SPECS:
        operation_ids = (
            spec.list_operation_id,
            spec.get_operation_id,
            spec.create_operation_id,
            *(action.operation_id for action in spec.actions),
        )
        for operation_id in operation_ids:
            if operation_id:
                covered[operation_id] = spec.key
    for destination, operation_ids in (
        ("configurations", CONFIGURATION_OPERATION_IDS.values()),
        ("secrets", SECRET_OPERATION_IDS.values()),
        ("deployment-recovery", DEPLOYMENT_OPERATION_IDS.values()),
        ("owners", OWNER_OPERATION_IDS.values()),
        ("provisioning", PROVISIONING_OPERATION_IDS.values()),
    ):
        for operation_id in operation_ids:
            covered[operation_id] = destination
    return covered


_WORKSPACE_OPERATIONS = _workspace_operations()
_OVERVIEW_OPERATIONS = frozenset({"platform_readiness_get", "platform_observability_get"})
# Deliberate exceptions live here. The generic renderer still provides a safe
# runtime fallback, but CI requires a conscious decision before a new operator
# operation may remain Advanced-only.
ADVANCED_ONLY_OPERATION_IDS: frozenset[str] = frozenset(
    {
        # The platform-owner read API is available through the generic
        # OpenAPI-driven advanced operations surface until a dedicated owner
        # workspace journey is designed and implemented.
        "platform_owner_get",
        "platform_owner_invitation_get",
        "platform_owner_invitation_list",
        "platform_owner_list",
    }
)


def classify_operation(operation: AdminOperation) -> SurfaceCoverage:
    """Classify an operation without copying any of its authority metadata."""

    if operation.console_flow:
        return SurfaceCoverage(operation.operation_id, "journey", operation.console_flow)
    if operation.operation_id in _OVERVIEW_OPERATIONS:
        return SurfaceCoverage(operation.operation_id, "workspace", "overview")
    workspace = _WORKSPACE_OPERATIONS.get(operation.operation_id)
    if workspace:
        return SurfaceCoverage(operation.operation_id, "workspace", workspace)
    return SurfaceCoverage(operation.operation_id, "advanced", "operations")


def coverage_registry(catalog: AdminCatalog) -> tuple[SurfaceCoverage, ...]:
    """Return one discoverability classification for every OpenAPI operation."""

    return tuple(classify_operation(operation) for operation in catalog.operations)


def coverage_counts(catalog: AdminCatalog) -> dict[str, int]:
    counts = {"journey": 0, "workspace": 0, "advanced": 0}
    for entry in coverage_registry(catalog):
        counts[entry.experience] += 1
    return counts


def operator_coverage_gaps(catalog: AdminCatalog) -> tuple[str, ...]:
    """Return operator operations that rely on the undeclared runtime fallback."""

    return tuple(
        operation.operation_id
        for operation in catalog.operations
        if operation.exposure == "operator"
        and classify_operation(operation).experience == "advanced"
        and operation.operation_id not in ADVANCED_ONLY_OPERATION_IDS
    )


def stale_surface_operation_ids(catalog: AdminCatalog) -> tuple[str, ...]:
    declared = (
        set(_WORKSPACE_OPERATIONS) | set(_OVERVIEW_OPERATIONS) | set(ADVANCED_ONLY_OPERATION_IDS)
    )
    return tuple(sorted(declared - set(catalog.by_id())))


__all__ = [
    "SurfaceCoverage",
    "ADVANCED_ONLY_OPERATION_IDS",
    "classify_operation",
    "coverage_counts",
    "coverage_registry",
    "operator_coverage_gaps",
    "stale_surface_operation_ids",
]
