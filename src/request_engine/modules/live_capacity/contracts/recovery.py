from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RecoveryCapacityCheckpoint:
    projection_policy_revision: int
    resource_availability_revision: int
    location_operational_revision: int


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
    executable_capacity_seconds: int
    committed_capacity_seconds: int
    shortfall_seconds: int
    source_fingerprint: str
    checkpoint: RecoveryCapacityCheckpoint
    affected_commitments: tuple[RecoveryCommitmentFact, ...]


class RecoveryCapacitySource(Protocol):
    async def assess_recovery_capacity(
        self,
        *,
        organization_id: UUID,
        service_queue_id: UUID,
    ) -> RecoveryCapacityAssessment: ...
