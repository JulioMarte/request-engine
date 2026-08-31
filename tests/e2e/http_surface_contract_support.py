from typing import cast

from request_engine.platform.security.capabilities import CapabilityDefinition

_OPERATION_ID_OVERRIDES = {
    "live_capacity.scope.update": "live_capacity_configure_scope_update",
    "live_capacity.estimate.update": "live_capacity_configure_estimate_update",
    "operational_recovery.intake_control": "operational_recovery_intake_control",
    "operational_recovery.extend_day": "operational_recovery_extend_day",
    "operational_recovery.reschedule_action": "operational_recovery_reschedule",
    "operational_recovery.replace_resource_action": "operational_recovery_replace_resource",
    "operational_recovery.communicate_impact": "operational_recovery_communicate_impact",
    "operational_copilot.tools.resources": "copilot_lookup_resources",
    "operational_copilot.tools.offerings": "copilot_lookup_offerings",
    "operational_copilot.tools.queues": "copilot_list_queues",
    "operational_copilot.tools.location_clock": "copilot_location_clock",
    "operational_copilot.tools.assignment_day_end": "copilot_assignment_day_end",
    "operational_copilot.tools.queue_intake": "copilot_queue_intake_state",
    "operational_copilot.tools.recovery_incident": "copilot_open_recovery_incident",
    "operational_copilot.tools.at_risk": "copilot_at_risk_reservations",
    "operational_copilot.tools.discovery_publication": "copilot_discovery_publication",
    "operational_copilot.tools.recovery_proposal": "copilot_propose_recovery",
    "operational_copilot.tools.recovery_execution": "copilot_execute_recovery",
    "operational_copilot.tools.recovery_intake": "copilot_set_recovery_intake",
    "operational_copilot.tools.day_extension": "copilot_extend_recovery_day",
    "operational_copilot.tools.discovery_publish": "copilot_publish_discovery_supply",
    "operational_copilot.tools.discovery_revoke": "copilot_revoke_discovery_publication",
}


def operation_contract(openapi: dict[str, object], *, path: str, method: str) -> dict[str, object]:
    paths_value = openapi.get("paths")
    assert isinstance(paths_value, dict)
    path_value = cast(dict[str, object], paths_value)[path]
    assert isinstance(path_value, dict)
    operation_value = cast(dict[str, object], path_value)[method.lower()]
    assert isinstance(operation_value, dict)
    return cast(dict[str, object], operation_value)


def header_parameters(operation: dict[str, object]) -> dict[str, bool]:
    parameters_value = operation.get("parameters", [])
    assert isinstance(parameters_value, list)
    headers: dict[str, bool] = {}
    for parameter_value in cast(list[object], parameters_value):
        assert isinstance(parameter_value, dict)
        parameter = cast(dict[str, object], parameter_value)
        if parameter.get("in") != "header":
            continue
        name = parameter.get("name")
        required = parameter.get("required", False)
        assert isinstance(name, str)
        assert isinstance(required, bool)
        headers[name.lower()] = required
    return headers


def expected_operation_id(name: str, definition: CapabilityDefinition) -> str:
    return _OPERATION_ID_OVERRIDES.get(name, definition.key.replace(".", "_"))
