from request_engine.modules.operational_copilot.contracts import (
    CopilotContext,
    CreateRecoveryProposalIntent,
    ExecuteRecoveryIntent,
    ExtendOperationalDayIntent,
    ExtendRecoveryDayIntent,
    PublishDiscoverySupplyIntent,
    RevokeDiscoveryPublicationIntent,
    SetOperationalIntakeIntent,
    SetRecoveryIntakeIntent,
    ShowAtRiskReservationsIntent,
    ValidatedCopilotIntent,
)
from request_engine.modules.operational_copilot.lowering import (
    discovery,
    inspection,
    proactive,
    recovery,
)
from request_engine.modules.operational_copilot.lowering.operations import CopilotOperation
from request_engine.modules.operational_copilot.lowering.workflow import (
    lower_extend_day,
    lower_set_intake,
)

_LOWERERS = {
    CreateRecoveryProposalIntent: recovery.lower_create_proposal,
    ExecuteRecoveryIntent: recovery.lower_execute,
    SetRecoveryIntakeIntent: lower_set_intake,
    ExtendRecoveryDayIntent: lower_extend_day,
    SetOperationalIntakeIntent: proactive.lower_set_operational_intake,
    ExtendOperationalDayIntent: proactive.lower_extend_operational_day,
    PublishDiscoverySupplyIntent: discovery.lower_publish,
    RevokeDiscoveryPublicationIntent: discovery.lower_revoke,
    ShowAtRiskReservationsIntent: inspection.lower_show_at_risk,
}

__all__ = ["CopilotOperation", "lower_copilot_intent"]


def lower_copilot_intent(
    context: CopilotContext,
    validated: ValidatedCopilotIntent,
) -> CopilotOperation:
    intent = validated.value
    lowerer = _LOWERERS.get(type(intent))
    if lowerer is None:
        raise TypeError(f"unsupported validated copilot intent: {type(intent).__name__}")
    return lowerer(intent, context)
