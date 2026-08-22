from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OperationalHttpOperation:
    name: str
    method: str
    path_template: str

    @property
    def operation_key(self) -> tuple[str, str]:
        return self.method, self.path_template


OPERATIONAL_HTTP_OPERATIONS: tuple[OperationalHttpOperation, ...] = (
    OperationalHttpOperation(
        "organization.profile",
        "PATCH",
        "/v1/operations/organization/profile",
    ),
    OperationalHttpOperation(
        "organization.contacts",
        "PUT",
        "/v1/operations/organization/contacts",
    ),
    OperationalHttpOperation("locations.create", "POST", "/v1/operations/locations"),
    OperationalHttpOperation(
        "locations.update",
        "PATCH",
        "/v1/operations/locations/{location_id}",
    ),
    OperationalHttpOperation(
        "locations.contacts",
        "PUT",
        "/v1/operations/locations/{location_id}/contacts",
    ),
    OperationalHttpOperation(
        "locations.hours",
        "PUT",
        "/v1/operations/locations/{location_id}/hours",
    ),
    OperationalHttpOperation(
        "locations.hours_exception",
        "PUT",
        "/v1/operations/locations/{location_id}/hours-exceptions",
    ),
    OperationalHttpOperation(
        "offering_version.booking_terms",
        "PUT",
        "/v1/operations/offering-versions/{offering_version_id}/booking-terms",
    ),
    OperationalHttpOperation(
        "resource_assignments.create",
        "POST",
        "/v1/operations/resource-assignments",
    ),
    OperationalHttpOperation(
        "resource_assignments.retire",
        "POST",
        "/v1/operations/resource-assignments/{assignment_id}/retire",
    ),
    OperationalHttpOperation(
        "resource_assignments.availability",
        "PUT",
        "/v1/operations/resource-assignments/{assignment_id}/availability",
    ),
    OperationalHttpOperation(
        "resource_assignments.exception",
        "PUT",
        "/v1/operations/resource-assignments/{assignment_id}/exceptions",
    ),
    OperationalHttpOperation(
        "resources.exception",
        "PUT",
        "/v1/operations/resources/{resource_id}/exceptions",
    ),
    OperationalHttpOperation("context_terms.create", "POST", "/v1/operations/context-terms"),
    OperationalHttpOperation(
        "context_terms.supersede",
        "POST",
        "/v1/operations/context-terms/{current_context_terms_id}/supersede",
    ),
)


def operational_keys() -> frozenset[tuple[str, str]]:
    return frozenset(operation.operation_key for operation in OPERATIONAL_HTTP_OPERATIONS)
