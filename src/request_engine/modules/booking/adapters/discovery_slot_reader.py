from sqlalchemy import text

from request_engine.modules.booking.adapters.db.appointment_availability_reader import (
    PostgresAppointmentAvailabilityReader,
)
from request_engine.modules.booking.application.queries.find_appointment_slots import (
    FindAppointmentSlotsQuery,
)
from request_engine.modules.booking.contracts.appointments import AppointmentSlot
from request_engine.modules.booking.contracts.discovery import PublishedSlotQuery
from request_engine.platform.db.session import SessionFactory, tenant_transaction


class PostgresPublishedSlotReader:
    """Booking-owned reader for the internal discovery availability gateway."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory
        self._reader = PostgresAppointmentAvailabilityReader(session_factory)

    async def find_published_slots(
        self,
        query: PublishedSlotQuery,
    ) -> tuple[AppointmentSlot, ...]:
        if not await self._scope_is_current(query):
            return ()
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

    async def _scope_is_current(self, query: PublishedSlotQuery) -> bool:
        async with tenant_transaction(self._session_factory, query.organization_id) as session:
            value = await session.scalar(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM request_engine.discovery_publications dp
                        JOIN request_engine.offering_service_classifications m
                          ON m.organization_id = dp.organization_id
                         AND m.offering_id = dp.offering_id
                         AND m.id = :mapping_id
                         AND m.revision = :mapping_revision
                         AND m.status = 'active'
                        JOIN request_engine.service_classifications sc
                          ON sc.id = m.service_classification_id
                         AND sc.status = 'active'
                        JOIN request_engine.offering_versions ov
                          ON ov.organization_id = dp.organization_id
                         AND ov.offering_id = dp.offering_id
                         AND ov.id = :offering_version_id
                         AND ov.bookable
                        WHERE dp.organization_id = :organization_id
                          AND dp.id = :publication_id
                          AND dp.revision = :publication_revision
                          AND dp.status = 'active'
                          AND dp.location_id = :location_id
                          AND (dp.resource_id IS NULL OR dp.resource_id = :resource_id)
                          AND dp.effective_during && tstzrange(
                              :window_start, :window_end, '[)'
                          )
                          AND NOT EXISTS (
                              SELECT 1
                              FROM request_engine.offering_versions newer
                              WHERE newer.organization_id = ov.organization_id
                                AND newer.offering_id = ov.offering_id
                                AND newer.version > ov.version
                          )
                    )
                    """
                ),
                {
                    "organization_id": query.organization_id,
                    "publication_id": query.publication_id,
                    "publication_revision": query.publication_revision,
                    "mapping_id": query.mapping_id,
                    "mapping_revision": query.mapping_revision,
                    "offering_version_id": query.offering_version_id,
                    "location_id": query.location_id,
                    "resource_id": query.resource_id,
                    "window_start": query.window_start,
                    "window_end": query.window_end,
                },
            )
        return value is True
