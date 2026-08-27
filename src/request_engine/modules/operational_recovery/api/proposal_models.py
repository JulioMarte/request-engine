from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from request_engine.modules.operational_recovery.api.model_common import (
    AffectedReservationView,
    RecoverySourceCheckpointView,
)
from request_engine.modules.operational_recovery.contracts.models import RescheduleProposal


class RecoveryProposalView(BaseModel):
    id: UUID
    service_queue_id: UUID
    resource_id: UUID
    location_id: UUID
    observed_at: datetime
    horizon_end: datetime
    source_fingerprint: str
    source_snapshot: dict[str, object]
    source_checkpoint: RecoverySourceCheckpointView
    proposal_fingerprint: str
    executable_capacity_seconds: int
    committed_capacity_seconds: int
    shortfall_seconds: int
    affected: tuple[AffectedReservationView, ...]
    created_at: datetime

    @classmethod
    def from_contract(cls, item: RescheduleProposal) -> "RecoveryProposalView":
        return cls(
            id=item.id,
            service_queue_id=item.service_queue_id,
            resource_id=item.resource_id,
            location_id=item.location_id,
            observed_at=item.observed_at,
            horizon_end=item.horizon_end,
            source_fingerprint=item.source_fingerprint,
            source_snapshot=item.source_snapshot,
            source_checkpoint=RecoverySourceCheckpointView.from_contract(item.source_checkpoint),
            proposal_fingerprint=item.proposal_fingerprint,
            executable_capacity_seconds=item.executable_capacity_seconds,
            committed_capacity_seconds=item.committed_capacity_seconds,
            shortfall_seconds=item.shortfall_seconds,
            affected=tuple(AffectedReservationView.from_contract(value) for value in item.affected),
            created_at=item.created_at,
        )
