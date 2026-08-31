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

__all__ = ["CopilotOperation", "lower_copilot_intent"]


def lower_copilot_intent(
    context: CopilotContext,
    validated: ValidatedCopilotIntent,
) -> CopilotOperation:
    intent = validated.value
    if isinstance(intent, CreateRecoveryProposalIntent):
        return recovery.lower_create_proposal(intent, context)
    if isinstance(intent, ExecuteRecoveryIntent):
        return recovery.lower_execute(intent, context)
    if isinstance(intent, SetRecoveryIntakeIntent):
        return lower_set_intake(intent, context)
    if isinstance(intent, ExtendRecoveryDayIntent):
        return lower_extend_day(intent, context)
    if isinstance(intent, SetOperationalIntakeIntent):
        return proactive.lower_set_operational_intake(intent, context)
    if isinstance(intent, ExtendOperationalDayIntent):
        return proactive.lower_extend_operational_day(intent, context)
    if isinstance(intent, PublishDiscoverySupplyIntent):
        return discovery.lower_publish(intent, context)
    if isinstance(intent, RevokeDiscoveryPublicationIntent):
        return discovery.lower_revoke(intent, context)
    if isinstance(intent, ShowAtRiskReservationsIntent):
        return inspection.lower_show_at_risk(intent, context)
    raise TypeError(f"unsupported validated copilot intent: {type(intent).__name__}")
