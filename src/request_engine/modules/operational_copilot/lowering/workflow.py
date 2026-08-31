from request_engine.modules.operational_copilot.contracts import (
    CopilotContext,
    ExtendRecoveryDayIntent,
    SetRecoveryIntakeIntent,
)
from request_engine.modules.operational_copilot.lowering.operations import CopilotOperation
from request_engine.modules.operational_recovery.contracts.workflow_commands import (
    ExtendRecoveryDayCommand,
    SetRecoveryIntakeCommand,
)


def lower_set_intake(intent: object, context: CopilotContext) -> CopilotOperation:
    if not isinstance(intent, SetRecoveryIntakeIntent):
        raise TypeError("unsupported intake intent")
    return SetRecoveryIntakeCommand(
        organization_id=context.organization_id,
        principal_id=context.principal_id,
        incident_id=intent.incident_id,
        expected_source_revision=intent.expected_source_revision,
        expected_intake_revision=intent.expected_intake_revision,
        accepting=intent.accepting,
        idempotency_key=context.idempotency_key,
        reason=intent.reason,
        effective_until=intent.effective_until,
    )


def lower_extend_day(intent: object, context: CopilotContext) -> CopilotOperation:
    if not isinstance(intent, ExtendRecoveryDayIntent):
        raise TypeError("unsupported extend-day intent")
    if context.authority_party_id is None:
        raise TypeError("extend-day lowering requires trusted authority party")
    return ExtendRecoveryDayCommand(
        organization_id=context.organization_id,
        principal_id=context.principal_id,
        authority_party_id=context.authority_party_id,
        incident_id=intent.incident_id,
        expected_source_revision=intent.expected_source_revision,
        assignment_id=intent.assignment_id,
        start_at=intent.start_at,
        end_at=intent.end_at,
        expected_location_operational_revision=intent.expected_location_operational_revision,
        expected_resource_availability_revision=intent.expected_resource_availability_revision,
        idempotency_key=context.idempotency_key,
        reason=intent.reason,
    )
