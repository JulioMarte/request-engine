from uuid import UUID

from sqlalchemy import text

from request_engine.modules.booking.contracts.onboarding import BookingOnboardingSupply
from request_engine.platform.db.session import SessionFactory, tenant_transaction


class PostgresBookingOnboardingReader:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def read_booking_supply(self, *, organization_id: UUID) -> BookingOnboardingSupply:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            supply_count = (
                await session.execute(
                    text(
                        """
                        SELECT count(DISTINCT r.id)
                        FROM request_engine.resources AS r
                        WHERE r.organization_id = :organization_id
                          AND r.active
                          AND EXISTS (
                              SELECT 1
                              FROM request_engine.resource_location_assignments AS a
                              JOIN request_engine.resource_location_availability AS w
                                ON w.organization_id = a.organization_id
                               AND w.resource_location_assignment_id = a.id
                               AND w.active
                              WHERE a.organization_id = r.organization_id
                                AND a.resource_id = r.id
                                AND a.status = 'active'
                          )
                        """
                    ),
                    {"organization_id": organization_id},
                )
            ).scalar_one()
            return BookingOnboardingSupply(resource_supply_count=int(supply_count))
