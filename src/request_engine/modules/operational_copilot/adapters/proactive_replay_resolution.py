from request_engine.modules.operational_copilot.contracts import (
    CopilotContext,
    SetOperationalIntakeIntent,
)
from request_engine.modules.operational_copilot.errors import CopilotResolutionFailed
from request_engine.modules.operational_copilot.references import StopWalkInsRestOfDayIntent
from request_engine.modules.queue.contracts.intake import QueueIntakeControlPort

_STOP_REASON = "operational copilot: stop accepting walk-ins for the rest of the day"


async def resolve_intake_replay(
    intake: QueueIntakeControlPort,
    context: CopilotContext,
    intent: StopWalkInsRestOfDayIntent,
) -> SetOperationalIntakeIntent | None:
    request = await intake.get_request_by_idempotency(
        context.organization_id,
        context.principal_id,
        context.idempotency_key,
    )
    if request is None:
        return None
    if request.accepting is not False or request.reason != _STOP_REASON:
        raise CopilotResolutionFailed(
            "idempotency key is already bound to an incompatible proactive operation"
        )
    return SetOperationalIntakeIntent(
        service_queue_id=request.service_queue_id,
        accepting=False,
        expected_intake_revision=request.expected_revision,
        reason=request.reason,
        effective_until=request.effective_until,
    )
