from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from request_engine.modules.operational_recovery.contracts.models import (
    AffectedReservation,
    RecoverySourceCheckpoint,
    RescheduleProposal,
)


class CopilotRecoveryProposalView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    service_queue_id: UUID
    resource_id: UUID
    location_id: UUID
    observed_at: datetime
    horizon_end: datetime
    source_fingerprint: str
    source_snapshot: dict[str, object]
    source_checkpoint: RecoverySourceCheckpoint
    proposal_fingerprint: str
    executable_capacity_seconds: int
    committed_capacity_seconds: int
    shortfall_seconds: int
    affected: tuple[AffectedReservation, ...]
    created_at: datetime

    @classmethod
    def from_contract(cls, proposal: RescheduleProposal) -> "CopilotRecoveryProposalView":
        return cls.model_validate(proposal)
