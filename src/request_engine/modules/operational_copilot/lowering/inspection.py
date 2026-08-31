from request_engine.modules.operational_copilot.contracts import (
    AtRiskReservationsQuery,
    CopilotContext,
    ShowAtRiskReservationsIntent,
)
from request_engine.modules.operational_copilot.lowering.operations import CopilotOperation


def lower_show_at_risk(intent: object, context: CopilotContext) -> CopilotOperation:
    if not isinstance(intent, ShowAtRiskReservationsIntent):
        raise TypeError("unsupported inspection intent")
    return AtRiskReservationsQuery(
        organization_id=context.organization_id,
        service_queue_id=intent.service_queue_id,
    )
