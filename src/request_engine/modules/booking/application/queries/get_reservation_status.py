from typing import Protocol
from uuid import UUID

from request_engine.modules.booking.contracts.appointments import Reservation


class ReservationReader(Protocol):
    async def get_reservation(
        self,
        organization_id: UUID,
        reservation_id: UUID,
    ) -> Reservation | None: ...


async def get_reservation_status(
    reader: ReservationReader,
    *,
    organization_id: UUID,
    reservation_id: UUID,
) -> Reservation | None:
    return await reader.get_reservation(organization_id, reservation_id)
