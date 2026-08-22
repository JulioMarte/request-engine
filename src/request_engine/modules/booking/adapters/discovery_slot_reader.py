from request_engine.modules.booking.adapters.db.appointment_availability_reader import (
    PostgresAppointmentAvailabilityReader,
)
from request_engine.modules.booking.application.queries.find_appointment_slots import (
    FindAppointmentSlotsQuery,
)
from request_engine.modules.booking.contracts.appointments import AppointmentSlot
from request_engine.modules.booking.contracts.discovery import PublishedSlotQuery
from request_engine.platform.db.session import SessionFactory


class PostgresPublishedSlotReader:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._reader = PostgresAppointmentAvailabilityReader(session_factory)

    async def find_published_slots(
        self,
        query: PublishedSlotQuery,
    ) -> tuple[AppointmentSlot, ...]:
        return await self._reader.find_slots(
            FindAppointmentSlotsQuery(
                organization_id=query.organization_id,
                offering_version_id=query.offering_version_id,
                window_start=query.window_start,
                window_end=query.window_end,
                location_id=query.location_id,
                resource_id=query.resource_id,
                limit=query.limit,
            )
        )
