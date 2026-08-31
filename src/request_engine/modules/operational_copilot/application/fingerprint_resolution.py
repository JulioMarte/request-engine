from uuid import UUID

from request_engine.modules.operational_copilot.application.ports import RecoveryProposalReader
from request_engine.modules.operational_copilot.contracts import (
    CopilotContext,
    ExecuteRecoveryIntent,
)
from request_engine.modules.operational_copilot.errors import CopilotResolutionFailed
from request_engine.modules.operational_recovery.contracts.models import RescheduleProposal


async def resolve_execute_fingerprints(
    reader: RecoveryProposalReader,
    context: CopilotContext,
    intent: ExecuteRecoveryIntent,
) -> ExecuteRecoveryIntent:
    supplied_source = intent.expected_source_fingerprint
    supplied_target = intent.expected_proposal_fingerprint
    if supplied_source is not None and supplied_target is not None:
        return intent
    if supplied_source is not None or supplied_target is not None:
        raise CopilotResolutionFailed("source and proposal fingerprints must be resolved together")
    proposal = await _read_proposal(reader, context, intent.proposal_id)
    return ExecuteRecoveryIntent(
        proposal_id=intent.proposal_id,
        reservation_id=intent.reservation_id,
        expected_source_fingerprint=proposal.source_fingerprint,
        expected_proposal_fingerprint=proposal.proposal_fingerprint,
        allow_subject_override=intent.allow_subject_override,
        notify=intent.notify,
    )


async def _read_proposal(
    reader: RecoveryProposalReader,
    context: CopilotContext,
    proposal_id: UUID,
) -> RescheduleProposal:
    try:
        return await reader.get_proposal(
            organization_id=context.organization_id,
            proposal_id=proposal_id,
        )
    except Exception as error:
        raise CopilotResolutionFailed(
            "proposal fingerprints could not be resolved from operational truth"
        ) from error
