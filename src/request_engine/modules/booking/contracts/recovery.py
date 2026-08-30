from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from request_engine.modules.booking.contracts.appointments import (
    AppointmentSlot,
    Reservation,
    ResourceChoice,
)


class RecoveryBookingConflict(Exception):
    pass


class RecoveryTargetUnavailable(Exception):
    pass


@dataclass(frozen=True, slots=True)
class RecoveryCommitmentCheckpoint:
    reservation_id: UUID
    revision: int
    starts_at: datetime
    ends_at: datetime


@dataclass(frozen=True, slots=True)
class RecoveryRescheduleRequest:
    organization_id: UUID
    principal_id: UUID
    reservation_id: UUID
    expected_revision: int
    start_at: datetime
    location_id: UUID | None
    resources: tuple[ResourceChoice, ...]
    source_service_queue_id: UUID
    expected_recovery_source_revision: int
    source_resource_id: UUID
    expected_source_resource_availability_revision: int
    source_location_id: UUID
    expected_source_location_operational_revision: int
    source_observed_at: datetime
    source_horizon_end: datetime
    expected_source_commitments: tuple[RecoveryCommitmentCheckpoint, ...]
    idempotency_key: str
    allow_subject_override: bool
    expected_planned_duration_minutes: int | None = None
    expected_amount: Decimal | None = None
    expected_currency: str | None = None
    expected_target_location_operational_revision: int | None = None
    expected_configuration_fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class RecoveryExternalBookingRequest:
    """Cross-Organization recovery booking of one discovered published option.

    The provider Organization owns the new commitment: the discovery handoff
    token is its standing publication consent, and the referral subject must
    already exist as an active party of that Organization."""

    organization_id: UUID
    source_organization_id: UUID
    reservation_id: UUID
    action_id: UUID
    option_id: str
    subject_party_id: UUID


@dataclass(frozen=True, slots=True)
class RecoveryDisposalRequest:
    """Cancellation of the degraded source commitment after the replacement
    commitment is secured in the provider Organization."""

    organization_id: UUID
    principal_id: UUID
    reservation_id: UUID
    expected_revision: int
    action_id: UUID
    reason: str | None = None


class RecoveryBookingPort(Protocol):
    async def find_recovery_slots(
        self,
        *,
        organization_id: UUID,
        offering_version_id: UUID,
        window_start: datetime,
        window_end: datetime,
        location_id: UUID | None,
        limit: int,
    ) -> tuple[AppointmentSlot, ...]: ...

    async def reschedule_for_recovery(self, request: RecoveryRescheduleRequest) -> Reservation: ...

    async def book_discovered_option(
        self, request: RecoveryExternalBookingRequest
    ) -> Reservation: ...

    async def cancel_for_recovery(self, request: RecoveryDisposalRequest) -> Reservation: ...
