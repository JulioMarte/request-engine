from request_engine.modules.operational_copilot.contracts import (
    CopilotContext,
    CreateRecoveryProposalIntent,
    ExecuteRecoveryIntent,
)
from request_engine.modules.operational_copilot.lowering.operations import CopilotOperation
from request_engine.modules.operational_recovery.contracts.commands import (
    CreateRecoveryProposalCommand,
    ExecuteRecoveryCommand,
)


def lower_create_proposal(intent: object, context: CopilotContext) -> CopilotOperation:
    if not isinstance(intent, CreateRecoveryProposalIntent):
        raise TypeError("unsupported create-proposal intent")
    return CreateRecoveryProposalCommand(
        organization_id=context.organization_id,
        principal_id=context.principal_id,
        service_queue_id=intent.service_queue_id,
        idempotency_key=context.idempotency_key,
        search_days=intent.search_days,
    )


def lower_execute(intent: object, context: CopilotContext) -> CopilotOperation:
    if not isinstance(intent, ExecuteRecoveryIntent):
        raise TypeError("unsupported execute intent")
    if intent.expected_source_fingerprint is None or intent.expected_proposal_fingerprint is None:
        raise TypeError("execute lowering requires resolved fingerprints")
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
