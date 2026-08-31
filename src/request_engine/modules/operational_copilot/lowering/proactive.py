from request_engine.modules.booking.contracts.operational_schedule import (
    OperationalAssignmentExtensionRequest,
)
from request_engine.modules.operational_copilot.contracts import (
    CopilotContext,
    ExtendOperationalDayIntent,
    SetOperationalIntakeIntent,
)
from request_engine.modules.queue.contracts.intake import SetQueueIntakeControlRequest


def lower_set_operational_intake(
    intent: SetOperationalIntakeIntent,
    context: CopilotContext,
) -> SetQueueIntakeControlRequest:
    return SetQueueIntakeControlRequest(
        organization_id=context.organization_id,
        principal_id=context.principal_id,
        service_queue_id=intent.service_queue_id,
        accepting=intent.accepting,
        expected_revision=intent.expected_intake_revision,
        idempotency_key=context.idempotency_key,
        reason=intent.reason,
        effective_until=intent.effective_until,
    )


def lower_extend_operational_day(
    intent: ExtendOperationalDayIntent,
    context: CopilotContext,
) -> OperationalAssignmentExtensionRequest:
    if context.authority_party_id is None:
        raise ValueError("authority party must be resolved before lowering")
    return OperationalAssignmentExtensionRequest(
        organization_id=context.organization_id,
        principal_id=context.principal_id,
        authority_party_id=context.authority_party_id,
        assignment_id=intent.assignment_id,
        start_at=intent.start_at,
        end_at=intent.end_at,
        expected_resource_availability_revision=intent.expected_resource_availability_revision,
        idempotency_key=context.idempotency_key,
        reason=intent.reason,
    )
