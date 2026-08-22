from __future__ import annotations

from dataclasses import dataclass

PROFILE_SCOPE = "operations.manage_profile"
SUPPLY_SCOPE = "operations.manage_supply"
TERMS_SCOPE = "operations.manage_terms"
OPAQUE_TARGET = "foreign target is indistinguishable from unavailable target"


@dataclass(frozen=True, slots=True)
class OperationalHttpOperation:
    name: str
    method: str
    path_template: str
    authority_scope: str
    revision_owner: str | None
    stale_semantics: str
    durable_effect: str
    idempotency_required: bool = True
    tenant_isolation: str = OPAQUE_TARGET

    @property
    def operation_key(self) -> tuple[str, str]:
        return self.method, self.path_template


_ROUTES = (
    ("organization.profile", "PATCH", "/v1/operations/organization/profile"),
    ("organization.contacts", "PUT", "/v1/operations/organization/contacts"),
    ("locations.create", "POST", "/v1/operations/locations"),
    ("locations.update", "PATCH", "/v1/operations/locations/{location_id}"),
    ("locations.contacts", "PUT", "/v1/operations/locations/{location_id}/contacts"),
    ("locations.hours", "PUT", "/v1/operations/locations/{location_id}/hours"),
    ("locations.hours_exception", "PUT", "/v1/operations/locations/{location_id}/hours-exceptions"),
    (
        "offering_version.booking_terms",
        "PUT",
        "/v1/operations/offering-versions/{offering_version_id}/booking-terms",
    ),
    ("resource_assignments.create", "POST", "/v1/operations/resource-assignments"),
    (
        "resource_assignments.retire",
        "POST",
        "/v1/operations/resource-assignments/{assignment_id}/retire",
    ),
    (
        "resource_assignments.availability",
        "PUT",
        "/v1/operations/resource-assignments/{assignment_id}/availability",
    ),
    (
        "resource_assignments.exception",
        "PUT",
        "/v1/operations/resource-assignments/{assignment_id}/exceptions",
    ),
    ("resources.exception", "PUT", "/v1/operations/resources/{resource_id}/exceptions"),
    ("context_terms.create", "POST", "/v1/operations/context-terms"),
    (
        "context_terms.supersede",
        "POST",
        "/v1/operations/context-terms/{current_context_terms_id}/supersede",
    ),
)

_PROFILE_NAMES = frozenset(name for name, _, _ in _ROUTES[:7])
_SUPPLY_NAMES = frozenset(name for name, _, _ in _ROUTES[8:13])
_REVISION_OWNERS = {
    "locations.update": "Location.operational_revision",
    "locations.hours": "Location.operational_revision",
    "locations.hours_exception": "Location.operational_revision",
    "resource_assignments.create": "Resource.availability_revision",
    "resource_assignments.retire": "Assignment.revision+Resource.availability_revision",
    "resource_assignments.availability": "Resource.availability_revision",
    "resource_assignments.exception": "Resource.availability_revision",
    "resources.exception": "Resource.availability_revision",
    "context_terms.supersede": "BookingContextTerms.revision",
}


def _scope(name: str) -> str:
    if name in _PROFILE_NAMES:
        return PROFILE_SCOPE
    if name in _SUPPLY_NAMES:
        return SUPPLY_SCOPE
    return TERMS_SCOPE


def _stale(name: str, revision_owner: str | None) -> str:
    if name == "context_terms.create":
        return "idempotency_or_temporal_conflict"
    if name == "resource_assignments.retire":
        return "expected_assignment_and_resource_revisions"
    return "expected_revision" if revision_owner else "idempotency_conflict_only"


def _operation(name: str, method: str, path: str) -> OperationalHttpOperation:
    revision_owner = _REVISION_OWNERS.get(name)
    return OperationalHttpOperation(
        name=name,
        method=method,
        path_template=path,
        authority_scope=_scope(name),
        revision_owner=revision_owner,
        stale_semantics=_stale(name, revision_owner),
        durable_effect=f"{name}+audit",
    )


OPERATIONAL_HTTP_OPERATIONS = tuple(_operation(*route) for route in _ROUTES)


def operational_keys() -> frozenset[tuple[str, str]]:
    return frozenset(operation.operation_key for operation in OPERATIONAL_HTTP_OPERATIONS)
