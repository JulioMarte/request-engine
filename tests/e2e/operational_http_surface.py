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


Spec = tuple[str, str, str, str, str | None, str, str]
_OP_SPECS: tuple[Spec, ...] = (
    (
        "organization.profile", "PATCH", "/v1/operations/organization/profile", PROFILE_SCOPE,
        None, "idempotency conflict only", "Organization profile + audit",
    ),
    (
        "organization.contacts", "PUT", "/v1/operations/organization/contacts", PROFILE_SCOPE,
        None, "idempotency conflict only", "Organization contacts + audit",
    ),
    (
        "locations.create", "POST", "/v1/operations/locations", PROFILE_SCOPE,
        None, "idempotency conflict only", "Location + audit",
    ),
    (
        "locations.update", "PATCH", "/v1/operations/locations/{location_id}", PROFILE_SCOPE,
        "Location.operational_revision", "expected operational revision",
        "Location profile revision + audit",
    ),
    (
        "locations.contacts", "PUT", "/v1/operations/locations/{location_id}/contacts",
        PROFILE_SCOPE, None, "idempotency conflict only", "Location contacts + audit",
    ),
    (
        "locations.hours", "PUT", "/v1/operations/locations/{location_id}/hours", PROFILE_SCOPE,
        "Location.operational_revision", "expected operational revision",
        "Location hours + revision + audit",
    ),
    (
        "locations.hours_exception", "PUT",
        "/v1/operations/locations/{location_id}/hours-exceptions", PROFILE_SCOPE,
        "Location.operational_revision", "expected operational revision",
        "Location hours exception + revision + audit",
    ),
    (
        "offering_version.booking_terms", "PUT",
        "/v1/operations/offering-versions/{offering_version_id}/booking-terms", TERMS_SCOPE,
        None, "idempotency conflict only", "OfferingVersion booking terms + audit",
    ),
    (
        "resource_assignments.create", "POST", "/v1/operations/resource-assignments",
        SUPPLY_SCOPE, "Resource.availability_revision", "expected resource availability revision",
        "ResourceLocationAssignment + resource revision + audit",
    ),
    (
        "resource_assignments.retire", "POST",
        "/v1/operations/resource-assignments/{assignment_id}/retire", SUPPLY_SCOPE,
        "Assignment.revision + Resource.availability_revision",
        "expected assignment and resource revisions", "Retired assignment + resource revision + audit",
    ),
    (
        "resource_assignments.availability", "PUT",
        "/v1/operations/resource-assignments/{assignment_id}/availability", SUPPLY_SCOPE,
        "Resource.availability_revision", "expected resource availability revision",
        "Assignment availability + resource revision + audit",
    ),
    (
        "resource_assignments.exception", "PUT",
        "/v1/operations/resource-assignments/{assignment_id}/exceptions", SUPPLY_SCOPE,
        "Resource.availability_revision", "expected resource availability revision",
        "Assignment exception + resource revision + audit",
    ),
    (
        "resources.exception", "PUT", "/v1/operations/resources/{resource_id}/exceptions",
        SUPPLY_SCOPE, "Resource.availability_revision", "expected resource availability revision",
        "Resource exception + resource revision + audit",
    ),
    (
        "context_terms.create", "POST", "/v1/operations/context-terms", TERMS_SCOPE,
        None, "idempotency/temporal conflict", "BookingContextTerms + audit",
    ),
    (
        "context_terms.supersede", "POST",
        "/v1/operations/context-terms/{current_context_terms_id}/supersede", TERMS_SCOPE,
        "BookingContextTerms.revision", "expected current revision",
        "Terms cutover + successor + audit",
    ),
)

OPERATIONAL_HTTP_OPERATIONS = tuple(OperationalHttpOperation(*spec) for spec in _OP_SPECS)


def operational_keys() -> frozenset[tuple[str, str]]:
    return frozenset(operation.operation_key for operation in OPERATIONAL_HTTP_OPERATIONS)
