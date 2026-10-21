"""Plain, unique names for configuration tasks, for display only.

This is interface copy, not policy: it never decides what an operation does,
who may run it or which owner handles it. The owner's OpenAPI summary is
written for integrators ("Create", "Offering") and repeats across sections, so
the console names each task by what a business person is doing. Unknown
operations fall back to the owner's summary, so a new task is never hidden.
"""

from __future__ import annotations

from typing import Any

_LABELS = {
    # Organization
    "parties_register": "Register a customer or contact",
    "business_get_info": "See business details",
    "tenancy_operational_authority_bootstrap": "Set up who can run the business",
    "tenancy_organization_profile_update": "Change business profile",
    "tenancy_organization_contacts_replace": "Change business contacts",
    # Locations and hours
    "catalog_location_configuration_list": "See all locations",
    "catalog_location_configuration_read": "See one location",
    "catalog_location_create": "Add a location",
    "catalog_location_update": "Change a location",
    "catalog_location_contacts_update": "Change a location's contacts",
    "catalog_location_hours_replace": "Change opening hours",
    "catalog_location_hours_exception_upsert": "Set special hours for a date",
    "catalog_organization_holidays_replace": "Set holidays",
    # Services and booking policies
    "catalog_offering_configuration_list": "See all services",
    "catalog_offering_configuration_read": "See one service",
    "catalog_resource_capabilities_list": "See skills and equipment types",
    "catalog_manage_resource_capabilities": "Add a skill or equipment type",
    "catalog_manage_offerings": "Add a service",
    "catalog_offering_version_configuration_read": "See a service's current settings",
    "catalog_manage_offering_version_booking_policy": "Change booking rules for a service",
    "catalog_offering_booking_terms_configure": "Set a service's price",
    # Resources and supply
    "booking_resource_list": "See doctors, rooms and equipment",
    "booking_resource_create": "Add a doctor, room or equipment",
    "booking_resource_assignment_list": "See who works where",
    "booking_resource_assignment_create": "Assign to a location",
    "booking_resource_assignment_retire": "End an assignment",
    "booking_resource_assignment_availability_list": "See weekly availability",
    "booking_resource_assignment_availability_replace": "Change weekly availability",
    "booking_resource_assignment_exception_list": "See time off at a location",
    "booking_resource_assignment_exception_set": "Set time off at a location",
    "booking_resource_exception_list": "See time off",
    "booking_resource_exception_set": "Set time off",
    "booking_context_terms_list": "See location-specific prices",
    "booking_context_terms_configure": "Set a location-specific price",
    "booking_context_terms_supersede": "Replace a location-specific price",
    # Service queues
    "queue_service_queue_configuration_list": "See all waiting lines",
    "queue_service_queue_configuration_read": "See one waiting line",
    "queue_service_queue_create": "Add a waiting line",
    # Requests and definitions
    "request_definitions_list": "See request types",
    "request_definition_read": "See one request type",
    "requests_list_inbox": "See the request inbox",
    "requests_read": "See one request",
    "request_definition_create": "Add a request type",
    "request_definition_version_publish": "Publish a new request form",
    "request_definition_set_active": "Turn a request type on or off",
    # Public discovery
    "discovery_offering_classification_set": "List a service publicly",
    "discovery_offering_classification_revoke": "Stop listing a service publicly",
    "discovery_resource_public_profile_set": "Set a public profile",
    "discovery_resource_public_profile_deactivate": "Hide a public profile",
    "discovery_supply_publish": "Publish availability",
    "discovery_publication_revoke": "Withdraw published availability",
    # Agents
    "agent_list": "See assistants",
    "agent_get": "See one assistant",
    "agent_provision": "Add an assistant",
    "agent_manage_authority": "Change what an assistant can do",
    "agent_policy_read": "See an assistant's safety limits",
    "agent_policy_replace": "Change an assistant's safety limits",
    "agent_suspend": "Pause or resume an assistant",
    "agent_credential_rotate": "Replace an assistant's key",
    # Integrations
    "integration_list": "See integrations",
    "integration_read": "See one integration",
    "integration_provision": "Add an integration",
    "integration_manage_authority": "Change what an integration can do",
    "integration_activate_command": "Turn on an integration",
    "integration_suspend": "Change an integration's status",
    "integration_suspend_command": "Pause an integration",
    "integration_revoke_command": "Remove an integration",
    "integration_credential_rotate": "Replace an integration's key",
    # Authority and controller policy
    "authority_read_self": "See your own permissions",
    "authority_inspect_resource": "Check who can act on an item",
    "delegation_create": "Delegate a task",
    "delegation_revoke": "Withdraw a delegated task",
    "controller_policy_adoption_request_create": "Request newer owner permissions",
    "controller_policy_adoption_request_get": "See a permissions request",
    "controller_policy_adoption_request_withdraw": "Withdraw a permissions request",
    "controller_policy_upgrade": "Upgrade owner permissions (operator)",
    # Identity connections
    "identity_binding_list": "See connected sign-ins",
    "identity_binding_get": "See one connected sign-in",
    "identity_binding_suspend": "Pause a connected sign-in",
    "identity_binding_reactivate": "Resume a connected sign-in",
    "identity_binding_revoke": "Remove a connected sign-in",
    "identity_exchange_publish": "Share a customer profile with another business",
    "identity_exchange_match": "Find a shared customer profile",
    "identity_exchange_adopt": "Adopt a shared customer profile",
    "identity_link_intent_create": "Start linking a sign-in",
    "identity_link_intent_confirm": "Confirm linking a sign-in",
    # Live capacity and recovery policies
    "live_capacity_configure_estimate": "Add a wait-time estimate rule",
    "live_capacity_configure_estimate_update": "Change a wait-time estimate rule",
    "live_capacity_configure_scope": "Add a capacity view rule",
    "live_capacity_configure_scope_update": "Change a capacity view rule",
    "live_capacity_read": "See a line's live capacity",
    "live_capacity_evaluate_intake": "Check whether a line can take more people",
    "operational_recovery_configure_autonomy": "Set automatic recovery for a line",
    "workload_list": "See service lengths",
    "workload_create": "Add a service length",
    "workload_update": "Change a service length",
    "workload_deactivate": "Retire a service length",
    # Communication channels
    "communications_channel_policy_get": "See how messages are sent",
    "communications_configure_channel_policy": "Choose how messages are sent",
}


def task_label(operation: Any) -> str:
    """The person-facing name of a configuration task."""

    operation_id = str(getattr(operation, "operation_id", "") or "")
    summary = getattr(operation, "summary", None)
    return _LABELS.get(operation_id) or summary or operation_id.replace("_", " ")
