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
    CONTROLLER_ADOPTION_OPERATION_IDS,
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
        ("controller-policy-adoptions", CONTROLLER_ADOPTION_OPERATION_IDS.values()),
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
ADVANCED_ONLY_OPERATION_IDS: frozenset[str] = frozenset()


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

# Tenant task grouping is presentation only. Runtime OpenAPI still supplies all
# authority, schemas, concurrency, methods and paths; these IDs grant nothing.
TENANT_CONFIGURATION_SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Negocio",
        (
            "parties_register",
            "business_get_info",
            "tenancy_operational_authority_bootstrap",
            "tenancy_organization_profile_update",
            "tenancy_organization_contacts_replace",
        ),
    ),
    (
        "Sedes y horarios",
        (
            "catalog_location_configuration_list",
            "catalog_location_configuration_read",
            "catalog_location_create",
            "catalog_location_update",
            "catalog_location_contacts_update",
            "catalog_location_hours_replace",
            "catalog_location_hours_exception_upsert",
            "catalog_organization_holidays_replace",
        ),
    ),
    (
        "Servicios y reglas de reserva",
        (
            "catalog_offering_configuration_list",
            "catalog_offering_configuration_read",
            "catalog_resource_capabilities_list",
            "catalog_manage_resource_capabilities",
            "catalog_manage_offerings",
            "catalog_offering_version_configuration_read",
            "catalog_manage_offering_version_booking_policy",
            "catalog_offering_booking_terms_configure",
        ),
    ),
    (
        "Médicos, consultorios y disponibilidad",
        (
            "booking_resource_list",
            "booking_resource_create",
            "booking_resource_assignment_list",
            "booking_resource_assignment_create",
            "booking_resource_assignment_retire",
            "booking_resource_assignment_availability_list",
            "booking_resource_assignment_availability_replace",
            "booking_resource_assignment_exception_list",
            "booking_resource_assignment_exception_set",
            "booking_resource_exception_list",
            "booking_resource_exception_set",
            "booking_context_terms_list",
            "booking_context_terms_configure",
            "booking_context_terms_supersede",
        ),
    ),
    (
        "Filas de espera",
        (
            "queue_service_queue_configuration_list",
            "queue_service_queue_configuration_read",
            "queue_service_queue_create",
        ),
    ),
    (
        "Solicitudes y tipos de solicitud",
        (
            "request_definitions_list",
            "request_definition_read",
            "requests_list_inbox",
            "requests_read",
            "request_definition_create",
            "request_definition_version_publish",
            "request_definition_set_active",
        ),
    ),
    (
        "Directorio público",
        (
            "discovery_offering_classification_set",
            "discovery_offering_classification_revoke",
            "discovery_resource_public_profile_set",
            "discovery_resource_public_profile_deactivate",
            "discovery_supply_publish",
            "discovery_publication_revoke",
        ),
    ),
    (
        "Asistentes",
        (
            "agent_list",
            "agent_get",
            "agent_provision",
            "agent_manage_authority",
            "agent_policy_read",
            "agent_policy_replace",
            "agent_suspend",
            "agent_credential_rotate",
        ),
    ),
    (
        "Integraciones",
        (
            "integration_list",
            "integration_read",
            "integration_provision",
            "integration_manage_authority",
            "integration_activate_command",
            "integration_suspend",
            "integration_suspend_command",
            "integration_revoke_command",
            "integration_credential_rotate",
        ),
    ),
    (
        "Permisos y control del dueño",
        (
            "authority_read_self",
            "authority_inspect_resource",
            "delegation_create",
            "delegation_revoke",
            "controller_policy_adoption_request_create",
            "controller_policy_adoption_request_get",
            "controller_policy_adoption_request_withdraw",
            "controller_policy_upgrade",
        ),
    ),
    (
        "Inicios de sesión conectados",
        (
            "identity_binding_list",
            "identity_binding_get",
            "identity_binding_suspend",
            "identity_binding_reactivate",
            "identity_binding_revoke",
            "identity_exchange_publish",
            "identity_exchange_match",
            "identity_exchange_adopt",
            "identity_link_intent_create",
            "identity_link_intent_confirm",
        ),
    ),
    (
        "Capacidad en vivo y recuperación",
        (
            "live_capacity_configure_estimate",
            "live_capacity_configure_estimate_update",
            "live_capacity_configure_scope",
            "live_capacity_configure_scope_update",
            "live_capacity_read",
            "live_capacity_evaluate_intake",
            "operational_recovery_configure_autonomy",
            "workload_list",
            "workload_create",
            "workload_update",
            "workload_deactivate",
        ),
    ),
    (
        "Canales de mensajes",
        ("communications_channel_policy_get", "communications_configure_channel_policy"),
    ),
)

TENANT_CONFIGURATION_OPERATION_IDS = frozenset(
    operation_id
    for _, operation_ids in TENANT_CONFIGURATION_SECTIONS
    for operation_id in operation_ids
)


# Explicit disposition of runtime operator operations outside business setup.
# This map is presentation evidence only, never permission or an alternate executor.
TENANT_RUNTIME_EXTERNAL_DESTINATIONS: dict[str, tuple[str, str]] = {}
for _destination, _reason, _ids in (
    (
        "tenant-staff",
        "Existing tenant staff and invitation workspaces",
        (
            "staff_authority_plan",
            "staff_get",
            "staff_history_list",
            "staff_invitation_create",
            "staff_invitation_get",
            "staff_invitation_list",
            "staff_invitation_proposal_approve",
            "staff_invitation_proposal_create",
            "staff_invitation_proposal_get",
            "staff_invitation_proposal_list",
            "staff_invitation_proposal_reject",
            "staff_invitation_resend",
            "staff_invitation_revoke",
            "staff_invite",
            "staff_list",
            "staff_manage_authority",
            "staff_manage_membership",
            "staff_overview_get",
            "staff_profile_update",
        ),
    ),
    (
        "tenant-readiness",
        "Read automatically by the business configuration overview",
        ("onboarding_read",),
    ),
    (
        "tenant-today",
        (
            "The Today front desk reads the live queue and day board and runs check-in, "
            "call next/now, set aside, no-show, skip, start and finish service; it also "
            "projects public booking, customer lookup and attendance operations "
            "(TODAY_OPERATION_IDS)"
        ),
        (
            "appointments_day_board",
            "queue_call_next",
            "queue_check_in",
            "queue_mark_no_show",
            "queue_operator_select",
            "queue_recall_hold",
            "queue_release_recall_hold",
            "queue_skip",
            "queue_staff_read",
            "service_session_complete",
            "service_session_start",
        ),
    ),
    (
        "operational-runtime-api",
        (
            "Daily service execution belongs to the operational client; "
            "no setup command or dashboard completion is inferred"
        ),
        (
            "operational_recovery_communicate_impact",
            "operational_recovery_execute",
            "operational_recovery_extend_day",
            "operational_recovery_intake_control",
            "operational_recovery_propose",
            "operational_recovery_read",
            "operational_recovery_replace_resource",
            "operational_recovery_reschedule",
            "queue_classify_expected_workload",
            "queue_staff_history_read",
            "resource_activity_end",
            "resource_activity_read",
            "resource_activity_start",
            "service_session_pause",
            "service_session_read",
            "service_session_resume",
        ),
    ),
    (
        "legacy-copilot-runtime-api",
        (
            "Existing migration-era copilot projection; "
            "canonical owner configuration is used by this admin panel"
        ),
        (
            "copilot_assignment_day_end",
            "copilot_at_risk_reservations",
            "copilot_discovery_publication",
            "copilot_execute_recovery",
            "copilot_extend_operational_day",
            "copilot_extend_recovery_day",
            "copilot_list_queues",
            "copilot_location_clock",
            "copilot_lookup_offerings",
            "copilot_lookup_resources",
            "copilot_open_recovery_incident",
            "copilot_propose_recovery",
            "copilot_publish_discovery_supply",
            "copilot_queue_intake_state",
            "copilot_recovery_proposal",
            "copilot_revoke_discovery_publication",
            "copilot_set_operational_intake",
            "copilot_set_recovery_intake",
            "operational_copilot_execute",
            "operational_copilot_interpret",
        ),
    ),
):
    for _operation_id in _ids:
        TENANT_RUNTIME_EXTERNAL_DESTINATIONS[_operation_id] = (_destination, _reason)
