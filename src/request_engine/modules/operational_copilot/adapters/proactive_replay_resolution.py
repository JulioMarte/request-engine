from request_engine.modules.booking.contracts.operational_schedule import (
    OperationalAssignmentSchedulePort,
)
from request_engine.modules.operational_copilot.contracts import (
    CopilotContext,
    ExtendOperationalDayIntent,
    SetOperationalIntakeIntent,
)
from request_engine.modules.operational_copilot.errors import CopilotResolutionFailed
from request_engine.modules.operational_copilot.references import (
    ExtendNamedResourceTodayIntent,
    StopWalkInsRestOfDayIntent,
)
from request_engine.modules.queue.contracts.intake import QueueIntakeControlPort

_STOP_REASON = "operational copilot: stop accepting walk-ins for the rest of the day"


async def resolve_proactive_replay(
    schedule: OperationalAssignmentSchedulePort,
    intake: QueueIntakeControlPort,
    context: CopilotContext,
    intent: ExtendNamedResourceTodayIntent | StopWalkInsRestOfDayIntent,
) -> ExtendOperationalDayIntent | SetOperationalIntakeIntent | None:
    if isinstance(intent, StopWalkInsRestOfDayIntent):
        request = await intake.get_request_by_idempotency(
            context.organization_id,
            context.principal_id,
            context.idempotency_key,
        )
        if request is None:
            return None
        if request.accepting is not False or request.reason != _STOP_REASON:
            raise _incompatible_replay()
        return SetOperationalIntakeIntent(
            service_queue_id=request.service_queue_id,
            accepting=False,
            expected_intake_revision=request.expected_revision,
            reason=request.reason,
            effective_until=request.effective_until,
        )

    replay = await schedule.get_extension_by_idempotency(
        context.organization_id,
        context.principal_id,
        context.idempotency_key,
    )
    if replay is None:
        return None
    target = intent.target_local_time
    end = replay.end_at
    expected_reason = f"operational copilot: extend {intent.resource_reference} today"
    if (
        replay.reason != expected_reason
        or (end.hour, end.minute, end.second, end.microsecond)
        != (target.hour, target.minute, target.second, target.microsecond)
    ):
        raise _incompatible_replay()
    return ExtendOperationalDayIntent(
        assignment_id=replay.assignment_id,
        start_at=replay.start_at,
        end_at=replay.end_at,
        expected_resource_availability_revision=(
            replay.expected_resource_availability_revision
        ),
        reason=replay.reason,
    )


def _incompatible_replay() -> CopilotResolutionFailed:
    return CopilotResolutionFailed(
        "idempotency key is already bound to an incompatible proactive operation"
    )
