from request_engine.modules.operational_copilot.contracts import (
    CopilotContext,
    CreateRecoveryProposalIntent,
    ExecuteRecoveryIntent,
    ValidatedCopilotIntent,
)
from request_engine.modules.operational_recovery.contracts.commands import (
    CreateRecoveryProposalCommand,
    ExecuteRecoveryCommand,
)

RecoveryCommand = CreateRecoveryProposalCommand | ExecuteRecoveryCommand


def lower_copilot_intent(
    context: CopilotContext,
    validated: ValidatedCopilotIntent,
) -> RecoveryCommand:
    intent = validated.value
    if isinstance(intent, CreateRecoveryProposalIntent):
        return CreateRecoveryProposalCommand(
            organization_id=context.organization_id,
            principal_id=context.principal_id,
            service_queue_id=intent.service_queue_id,
            idempotency_key=context.idempotency_key,
            search_days=intent.search_days,
        )
    if isinstance(intent, ExecuteRecoveryIntent):
        return ExecuteRecoveryCommand(
            organization_id=context.organization_id,
            principal_id=context.principal_id,
            proposal_id=intent.proposal_id,
            reservation_id=intent.reservation_id,
            expected_source_fingerprint=intent.expected_source_fingerprint,
            expected_proposal_fingerprint=intent.expected_proposal_fingerprint,
            idempotency_key=context.idempotency_key,
            allow_subject_override=intent.allow_subject_override,
            notify=intent.notify,
        )
    raise TypeError(f"unsupported validated copilot intent: {type(intent).__name__}")
