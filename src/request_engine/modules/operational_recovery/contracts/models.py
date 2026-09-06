from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from request_engine.modules.booking.contracts.appointments import ResourceChoice


class RecoveryExecutionStatus(StrEnum):
    PREPARED = "prepared"
    SUCCEEDED = "succeeded"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class RecoveryCommitmentCheckpoint:
    reservation_id: UUID
    revision: int
    starts_at: datetime
    ends_at: datetime


@dataclass(frozen=True, slots=True)
class RecoverySourceCheckpoint:
    projection_policy_revision: int
    resource_availability_revision: int
    location_operational_revision: int
    recovery_source_revision: int
    commitments: tuple[RecoveryCommitmentCheckpoint, ...]


@dataclass(frozen=True, slots=True)
class RecoveryTarget:
    start_at: datetime
    end_at: datetime
    location_id: UUID | None
    resources: tuple[ResourceChoice, ...]
    actionable: bool
    blocked_reason: str | None = None
    planned_duration_minutes: int | None = None
    amount: Decimal | None = None
    currency: str | None = None
    location_operational_revision: int | None = None
    configuration_fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class AffectedReservation:
    reservation_id: UUID
    offering_version_id: UUID
    subject_party_id: UUID
    expected_revision: int
    original_start_at: datetime
    original_end_at: datetime
    target: RecoveryTarget | None
    replacement_target: RecoveryTarget | None = None


@dataclass(frozen=True, slots=True)
class RescheduleProposal:
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


@dataclass(frozen=True, slots=True)
class OperationalNotification:
    requested: bool
    communication_task_id: UUID | None


@dataclass(frozen=True, slots=True)
class RecoveryExecution:
    id: UUID
    proposal_id: UUID
    reservation_id: UUID
    status: RecoveryExecutionStatus
    original_reservation_revision: int
    resulting_reservation_revision: int | None
    target: RecoveryTarget
    created_at: datetime
    completed_at: datetime | None
    failure_code: str | None
    notification: OperationalNotification
