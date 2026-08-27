from uuid import UUID

from pydantic import BaseModel, Field

from request_engine.modules.operational_recovery.api.execution_models import RecoveryExecutionView
from request_engine.modules.operational_recovery.api.model_common import (
    AffectedReservationView,
    RecoveryCommitmentCheckpointView,
    RecoveryResourceChoiceView,
    RecoverySourceCheckpointView,
    RecoveryTargetView,
)
from request_engine.modules.operational_recovery.api.proposal_models import RecoveryProposalView


class CreateRecoveryProposalBody(BaseModel):
    search_days: int = Field(default=7, ge=1, le=30)


class ExecuteRecoveryBody(BaseModel):
    reservation_id: UUID
    expected_source_fingerprint: str = Field(min_length=1)
    expected_proposal_fingerprint: str = Field(min_length=1)
    notify: bool = True


__all__ = [
    "AffectedReservationView",
    "CreateRecoveryProposalBody",
    "ExecuteRecoveryBody",
    "RecoveryCommitmentCheckpointView",
    "RecoveryExecutionView",
    "RecoveryProposalView",
    "RecoveryResourceChoiceView",
    "RecoverySourceCheckpointView",
    "RecoveryTargetView",
]
