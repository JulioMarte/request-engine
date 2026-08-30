from datetime import datetime
from uuid import UUID

from request_engine.modules.booking.adapters.db.appointment_availability_reader import (
    PostgresAppointmentAvailabilityReader,
)
from request_engine.modules.booking.adapters.db.recovery_external import (
    PostgresRecoveryExternalBooking,
)
from request_engine.modules.booking.adapters.db.recovery_reschedule import (
    PostgresGuardedRecoveryReschedule,
)
from request_engine.modules.booking.application.errors import (
    AppointmentOptionInvalid,
    AppointmentOptionStale,
    OfferingVersionNotBookable,
    OfferingVersionNotFound,
    SubjectAuthorityRequired,
)
from request_engine.modules.booking.application.queries.find_appointment_slots import (
    FindAppointmentSlotsQuery,
)
from request_engine.modules.booking.contracts.appointments import AppointmentSlot, Reservation
from request_engine.modules.booking.contracts.recovery import (
    RecoveryBookingPort,
    RecoveryDisposalRequest,
    RecoveryExternalBookingRequest,
    RecoveryRescheduleRequest,
    RecoveryTargetUnavailable,
)
from request_engine.platform.db.session import SessionFactory


class PostgresRecoveryBookingPort(RecoveryBookingPort):
    def __init__(self, session_factory: SessionFactory) -> None:
        self._availability = PostgresAppointmentAvailabilityReader(session_factory)
        self._reschedule = PostgresGuardedRecoveryReschedule(session_factory)
        self._external = PostgresRecoveryExternalBooking(session_factory)

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
        return await self._reschedule.reschedule(request)

    async def book_discovered_option(self, request: RecoveryExternalBookingRequest) -> Reservation:
        try:
            return await self._external.book_discovered_option(request)
        except (
            AppointmentOptionInvalid,
            AppointmentOptionStale,
            OfferingVersionNotBookable,
            OfferingVersionNotFound,
            SubjectAuthorityRequired,
        ) as exc:
            raise RecoveryTargetUnavailable(request.reservation_id, str(exc)) from exc

    async def cancel_for_recovery(self, request: RecoveryDisposalRequest) -> Reservation:
        return await self._external.cancel_for_recovery(request)
