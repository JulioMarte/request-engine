from request_engine.platform.security.capability_types import (
    CapabilityDefinition,
    CapabilityExposure,
    command_capability,
    query_capability,
)
from request_engine.platform.security.operation_risk import OperationRiskClass

BOOKING_DAY_BOARD_CAPABILITIES: tuple[CapabilityDefinition, ...] = (
    query_capability(
        "appointments.day_board",
        CapabilityExposure.OPERATOR,
        "Read the bounded operator reservation day board without per-subject authority.",
    ),
    command_capability(
        "appointments.annotate",
        CapabilityExposure.OPERATOR,
        "Add an append-only staff note to an appointment without per-subject authority.",
        risk_class=OperationRiskClass.LOW_IMPACT_WRITE,
    ),
)
