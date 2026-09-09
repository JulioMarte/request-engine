from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID

from request_engine.modules.booking.contracts.appointments import (
    Reservation,
    ReservationStatus,
    ResourceChoice,
)
from request_engine.modules.booking.contracts.recovery import RecoveryRescheduleRequest
from request_engine.modules.operational_recovery.application.ports import RecoveryRepository
from request_engine.modules.operational_recovery.application.workflow_commands import (
    RescheduleRecoveryActionCommand,
)
from request_engine.modules.operational_recovery.contracts.models import (
    AffectedReservation,
    RecoverySourceCheckpoint,
    RecoveryTarget,
    RescheduleProposal,
)

NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
ORG, PRINCIPAL = UUID(int=1), UUID(int=2)
INCIDENT, QUEUE, RESOURCE, LOCATION = UUID(int=4), UUID(int=5), UUID(int=6), UUID(int=7)
PROPOSAL, RESERVATION, REQUIREMENT = UUID(int=20), UUID(int=21), UUID(int=22)


class FakeProposalRepository:
    def __init__(self, proposal: RescheduleProposal) -> None:
        self.proposal = proposal

    async def get_proposal(self, *, organization_id: UUID, proposal_id: UUID):
        if organization_id == ORG and proposal_id == PROPOSAL:
            return self.proposal
        return None

    def as_port(self) -> RecoveryRepository:
        return cast(RecoveryRepository, self)


class FakeBooking:
    def __init__(self, fail_once: bool = False) -> None:
        self.requests: list[RecoveryRescheduleRequest] = []
        self.fail_once = fail_once

    async def reschedule_for_recovery(self, request: RecoveryRescheduleRequest) -> Reservation:
        self.requests.append(request)
        if self.fail_once:
            self.fail_once = False
            raise TimeoutError("simulated response loss after Booking commit")
        return Reservation(
            id=request.reservation_id,
            offering_version_id=UUID(int=30),
            subject_party_id=UUID(int=31),
            location_id=request.location_id,
            start_at=request.start_at,
            end_at=request.start_at + timedelta(hours=1),
            status=ReservationStatus.CONFIRMED,
            revision=2,
        )


def proposal() -> RescheduleProposal:
    target = RecoveryTarget(
        start_at=NOW + timedelta(hours=2),
        end_at=NOW + timedelta(hours=3),
        location_id=LOCATION,
        resources=(
            ResourceChoice(
                requirement_id=REQUIREMENT,
                resource_id=RESOURCE,
                resource_location_assignment_id=UUID(int=23),
                assignment_revision=1,
                availability_revision=1,
            ),
        ),
        planned_duration_minutes=60,
        amount=Decimal("3500"),
        currency="DOP",
        location_operational_revision=1,
        configuration_fingerprint="sha256:workflow-reschedule-target",
    )
    affected = AffectedReservation(
        RESERVATION,
        UUID(int=30),
        UUID(int=31),
        1,
        NOW,
        NOW + timedelta(hours=1),
        target,
    )
    return RescheduleProposal(
        PROPOSAL,
        QUEUE,
        RESOURCE,
        LOCATION,
        NOW,
        NOW + timedelta(hours=8),
        "source:v3",
        {},
        RecoverySourceCheckpoint(1, 1, 1, 3, ()),
        "proposal:v3",
        3600,
        7200,
        3600,
        (affected,),
        NOW,
    )


def command() -> RescheduleRecoveryActionCommand:
    return RescheduleRecoveryActionCommand(
        ORG,
        PRINCIPAL,
        INCIDENT,
        3,
        PROPOSAL,
        RESERVATION,
        "source:v3",
        "proposal:v3",
        "reschedule-action-1",
        True,
    )
