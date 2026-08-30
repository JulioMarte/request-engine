from request_engine.modules.operational_recovery.application.service import (
    OperationalRecoveryService,
)
from request_engine.modules.operational_recovery.contracts.queries import RecoveryProposalReader

__all__ = ["build_recovery_proposal_reader"]


def build_recovery_proposal_reader(
    service: OperationalRecoveryService,
) -> RecoveryProposalReader:
    """Publish the recovery proposal read surface for composition roots.

    OperationalRecoveryService.get_proposal satisfies the published
    RecoveryProposalReader protocol structurally; no new application logic.
    """
    return service
