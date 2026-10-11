"""Classify owner configuration discovery and Request-definition Commands."""

from .http_surface import PROBE_UUID, HttpProbe, PublicHttpOperation, TenantIsolationMode

_READS = (
    ("booking_resource_list", "/v1/booking/resources", "booking.read_supply", True, False),
    (
        "booking_resource_exception_list",
        "/v1/booking/resources/{resource_id}/exceptions",
        "booking.read_supply",
        True,
        False,
    ),
    (
        "catalog_offering_version_configuration_read",
        "/v1/catalog/offering-versions/{offering_version_id}/configuration",
        "catalog.read_configuration",
        True,
        True,
    ),
    (
        "catalog_resource_capabilities_list",
        "/v1/catalog/resource-capabilities",
        "catalog.read_configuration",
        False,
        False,
    ),
    (
        "communications_channel_policy_get",
        "/v1/communications/channel-policies/{purpose}",
        "communications.read_configuration",
        True,
        False,
    ),
    (
        "booking_context_terms_list",
        "/v1/operations/context-terms",
        "booking.read_supply",
        True,
        False,
    ),
    (
        "booking_resource_assignment_list",
        "/v1/operations/resource-assignments",
        "booking.read_supply",
        True,
        False,
    ),
    (
        "booking_resource_assignment_availability_list",
        "/v1/operations/resource-assignments/{assignment_id}/availability",
        "booking.read_supply",
        True,
        False,
    ),
    (
        "booking_resource_assignment_exception_list",
        "/v1/operations/resource-assignments/{assignment_id}/exceptions",
        "booking.read_supply",
        True,
        False,
    ),
    (
        "request_definitions_list",
        "/v1/request-definitions",
        "requests.read_definitions",
        False,
        False,
    ),
    (
        "request_definition_read",
        "/v1/request-definitions/{definition_id}",
        "requests.read_definitions",
        False,
        True,
    ),
    ("requests_list_inbox", "/v1/requests", "requests.read_inbox", False, False),
)


def _read(name: str, path: str, capability: str, party: bool, detail: bool) -> PublicHttpOperation:
    probe = path.replace("{purpose}", "appointment_confirmation")
    for parameter in ("resource_id", "offering_version_id", "assignment_id", "definition_id"):
        probe = probe.replace("{" + parameter + "}", PROBE_UUID)
    return PublicHttpOperation(
        name,
        "GET",
        path,
        capability,
        False,
        False,
        TenantIsolationMode.NOT_FOUND if detail else TenantIsolationMode.FILTERED,
        HttpProbe(probe, query=(("authority_party_id", PROBE_UUID),) if party else ()),
    )


ADMINISTRATIVE_CONFIGURATION_HTTP_OPERATIONS = tuple(_read(*row) for row in _READS) + (
    PublicHttpOperation(
        "agent_credential_rotate",
        "POST",
        "/v1/agents/{agent_principal_id}/credentials:rotate",
        "agent.manage_authority",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            f"/v1/agents/{PROBE_UUID}/credentials:rotate",
            body={
                "expected_authority_revision": 1,
                "credential_expires_at": "2099-01-01T00:00:00Z",
                "provenance_reference": "classification-proof",
            },
        ),
    ),
    PublicHttpOperation(
        "request_definition_create",
        "POST",
        "/v1/request-definitions",
        "requests.create_definition",
        True,
        True,
        TenantIsolationMode.CONTEXTUAL,
        HttpProbe(
            "/v1/request-definitions",
            body={
                "authority_party_id": PROBE_UUID,
                "request_key": "classification-proof",
                "display_name": "Classification proof",
                "input_schema": {"type": "object"},
            },
        ),
    ),
    PublicHttpOperation(
        "request_definition_version_publish",
        "POST",
        "/v1/request-definitions/{definition_id}/versions",
        "requests.publish_definition_version",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            f"/v1/request-definitions/{PROBE_UUID}/versions",
            body={
                "authority_party_id": PROBE_UUID,
                "expected_revision": 1,
                "input_schema": {"type": "object"},
            },
        ),
    ),
    PublicHttpOperation(
        "request_definition_set_active",
        "POST",
        "/v1/request-definitions/{definition_id}:set-active",
        "requests.set_definition_active",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            f"/v1/request-definitions/{PROBE_UUID}:set-active",
            body={
                "authority_party_id": PROBE_UUID,
                "expected_revision": 1,
                "active": False,
            },
        ),
    ),
)

ADMINISTRATIVE_CONFIGURATION_OPERATION_IDS = frozenset(
    operation.name for operation in ADMINISTRATIVE_CONFIGURATION_HTTP_OPERATIONS
)
