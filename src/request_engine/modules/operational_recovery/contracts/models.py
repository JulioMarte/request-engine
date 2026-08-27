from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from request_engine.modules.booking.contracts.appointments import ResourceChoice


@dataclass(frozen=True, slots=True)
class RecoveryTarget:
    start_at: datetime
    end_at: datetime
    location_id: UUID | None
    resources: tuple[ResourceChoice, ...]
    actionable: bool
    blocked_reason: str | None = None


@dataclass(frozen=True, slots=True)
class AffectedReservation:
    reservation_id: UUID
    offering_version_id: UUID
    subject_party_id: UUID
    expected_revision: int
    original_start_at: datetime
    original_end_at: datetime
    target: RecoveryTarget | None


@dataclass(frozen=True, slots=True)
class RescheduleProposal:
    id: UUID
    service_queue_id: UUID
    resource_id: UUID
    location_id: UUID
    observed_at: datetime
    horizon_end: datetime
    source_fingerprint: str
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
    original_reservation_revision: int
    resulting_reservation_revision: int
    target: RecoveryTarget
    executed_at: datetime
    notification: OperationalNotification
