from datetime import datetime
from uuid import UUID

from request_engine.modules.booking.adapters.db.appointment_availability_reader import PostgresAppointmentAvailabilityReader
from request_engine.modules.booking.adapters.db.capacity_error_boundary import CapacitySafeBookingCommitmentCommands
from request_engine.modules.booking.adapters.db.reservation_reader import PostgresReservationReader
from request_engine.modules.booking.application.commands.reschedule_reservation import RescheduleReservationCommand
from request_engine.modules.booking.application.errors import (
    AppointmentUnavailable,
    ContextualCommitmentUnsupported,
    InvalidResourceSelection,
    ReservationNotReschedulable,
    ReservationRevisionConflict,
)
from request_engine.modules.booking.application.queries.find_appointment_slots import FindAppointmentSlotsQuery
from request_engine.modules.booking.contracts.appointments import AppointmentSlot, Reservation
from request_engine.modules.booking.contracts.recovery import (
    RecoveryBookingConflict,
    RecoveryBookingPort,
    RecoveryRescheduleRequest,
    RecoveryTargetUnavailable,
)
from request_engine.platform.db.session import SessionFactory


class PostgresRecoveryBookingPort(RecoveryBookingPort):
    def __init__(self, session_factory: SessionFactory) -> None:
        self._reader = PostgresReservationReader(session_factory)
        self._availability = PostgresAppointmentAvailabilityReader(session_factory)
        self._commands = CapacitySafeBookingCommitmentCommands(session_factory)

    async def get_reservation(
        self, *, organization_id: UUID, reservation_id: UUID
    ) -> Reservation | None:
        return await self._reader.get_reservation(organization_id, reservation_id)

    async def find_recovery_slots(
        self,
        *,
        organization_id: UUID,
        offering_version_id: UUID,
        window_start: datetime,
        window_end: datetime,
        location_id: UUID | None,
        limit: int,
    ) -> tuple[AppointmentSlot, ...]:
        return await self._availability.find_slots(
            FindAppointmentSlotsQuery(
                organization_id=organization_id,
                offering_version_id=offering_version_id,
                window_start=window_start,
                window_end=window_end,
                location_id=location_id,
                limit=limit,
            )
        )

    async def reschedule_for_recovery(self, request: RecoveryRescheduleRequest) -> Reservation:
        try:
            return await self._commands.reschedule_reservation(
                RescheduleReservationCommand(
                    organization_id=request.organization_id,
                    principal_id=request.principal_id,
                    reservation_id=request.reservation_id,
                    start_at=request.start_at,
                    resources=request.resources,
                    location_id=request.location_id,
                    idempotency_key=request.idempotency_key,
                    expected_revision=request.expected_revision,
                    allow_subject_override=request.allow_subject_override,
                )
            )
        except ReservationRevisionConflict as exc:
            raise RecoveryBookingConflict(str(exc)) from exc
        except (
            AppointmentUnavailable,
            ContextualCommitmentUnsupported,
            InvalidResourceSelection,
            ReservationNotReschedulable,
        ) as exc:
            raise RecoveryTargetUnavailable(str(exc)) from exc
