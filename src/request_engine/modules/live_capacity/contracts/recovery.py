from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from request_engine.modules.live_capacity.contracts.projection import (
    ProjectionReason,
    ProjectionState,
)


@dataclass(frozen=True, slots=True)
class RecoveryCommitmentCheckpoint:
    reservation_id: UUID
    revision: int
    starts_at: datetime
    ends_at: datetime


@dataclass(frozen=True, slots=True)
class RecoveryCapacityCheckpoint:
    projection_policy_revision: int
    resource_availability_revision: int
    location_operational_revision: int
    recovery_source_revision: int
    commitments: tuple[RecoveryCommitmentCheckpoint, ...]


@dataclass(frozen=True, slots=True)
class RecoveryCommitmentFact:
    reservation_id: UUID
    offering_version_id: UUID
    subject_party_id: UUID
    reservation_revision: int
    planned_starts_at: datetime
    planned_ends_at: datetime
    planned_duration_seconds: int


@dataclass(frozen=True, slots=True)
class RecoveryCapacityAssessment:
    service_queue_id: UUID
    resource_id: UUID
    location_id: UUID
    observed_at: datetime
    horizon_end: datetime
    projection_state: ProjectionState
    projection_reasons: tuple[ProjectionReason, ...]
    executable_capacity_seconds: int
    committed_capacity_seconds: int
    scheduled_shortfall_seconds: int
    live_shortfall_seconds: int
    shortfall_seconds: int
    source_fingerprint: str
    source_snapshot: dict[str, object]
    checkpoint: RecoveryCapacityCheckpoint
    affected_commitments: tuple[RecoveryCommitmentFact, ...]


class RecoveryCapacitySource(Protocol):
    async def assess_recovery_capacity(
        self,
        *,
        organization_id: UUID,
        service_queue_id: UUID,
    ) -> RecoveryCapacityAssessment: ...
