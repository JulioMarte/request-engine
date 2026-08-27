from datetime import datetime
from uuid import UUID

from request_engine.modules.booking.adapters.db.appointment_availability_reader import (
    PostgresAppointmentAvailabilityReader,
)
from request_engine.modules.booking.adapters.db.recovery_reschedule import (
    PostgresGuardedRecoveryReschedule,
)
from request_engine.modules.booking.application.queries.find_appointment_slots import (
    FindAppointmentSlotsQuery,
)
from request_engine.modules.booking.contracts.appointments import AppointmentSlot, Reservation
from request_engine.modules.booking.contracts.recovery import (
    RecoveryBookingPort,
    RecoveryRescheduleRequest,
)
from request_engine.platform.db.session import SessionFactory


class PostgresRecoveryBookingPort(RecoveryBookingPort):
    def __init__(self, session_factory: SessionFactory) -> None:
        self._availability = PostgresAppointmentAvailabilityReader(session_factory)
        self._reschedule = PostgresGuardedRecoveryReschedule(session_factory)

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
