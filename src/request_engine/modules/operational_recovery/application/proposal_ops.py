from uuid import UUID

from request_engine.modules.booking.contracts.recovery import RecoveryBookingPort
from request_engine.modules.live_capacity.contracts.recovery import RecoveryCapacitySource
from request_engine.modules.operational_recovery.application.commands import CreateRecoveryProposalCommand
from request_engine.modules.operational_recovery.application.errors import (
    RecoveryProposalNotFound,
    RecoveryShortfallNotMaterial,
)
from request_engine.modules.operational_recovery.application.fingerprints import (
    proposal_command_fingerprint,
)
from request_engine.modules.operational_recovery.application.ports import RecoveryRepository
from request_engine.modules.operational_recovery.application.proposal_builder import build_proposal
from request_engine.modules.operational_recovery.contracts.models import RescheduleProposal


async def create_proposal(
    command: CreateRecoveryProposalCommand,
    *,
    repository: RecoveryRepository,
    capacity: RecoveryCapacitySource,
    booking: RecoveryBookingPort,
) -> RescheduleProposal:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if command.search_days <= 0 or command.search_days > 30:
        raise ValueError("search_days must be between 1 and 30")
    fingerprint = proposal_command_fingerprint(command)
    replay = await repository.find_proposal_replay(
        organization_id=command.organization_id,
        principal_id=command.principal_id,
        idempotency_key=command.idempotency_key,
        command_fingerprint=fingerprint,
    )
    if replay is not None:
        return replay
    assessment = await capacity.assess_recovery_capacity(
        organization_id=command.organization_id,
        service_queue_id=command.service_queue_id,
    )
    if assessment.shortfall_seconds <= 0:
        raise RecoveryShortfallNotMaterial()
    if not assessment.affected_commitments:
        raise RuntimeError("positive recovery shortfall has no directly unsatisfied Reservations")
    proposal = await build_proposal(command=command, assessment=assessment, booking=booking)
    return await repository.create_proposal(
        organization_id=command.organization_id,
        principal_id=command.principal_id,
        idempotency_key=command.idempotency_key,
        command_fingerprint=fingerprint,
        proposal=proposal,
    )


async def get_proposal(
    *, repository: RecoveryRepository, organization_id: UUID, proposal_id: UUID
) -> RescheduleProposal:
    proposal = await repository.get_proposal(
        organization_id=organization_id,
        proposal_id=proposal_id,
    )
    if proposal is None:
        raise RecoveryProposalNotFound(proposal_id)
    return proposal
