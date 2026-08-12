from typing import Protocol
from uuid import UUID

from request_engine.modules.booking.application.authority import MANAGE_APPOINTMENT_SCOPE
from request_engine.modules.booking.application.errors import SubjectAuthorityRequired
from request_engine.modules.booking.contracts.appointments import Reservation
from request_engine.modules.tenancy.contracts.authority import PartyAuthorityReader


class ReservationReader(Protocol):
    async def get_reservation(
        self,
        organization_id: UUID,
        reservation_id: UUID,
    ) -> Reservation | None: ...


async def get_reservation_status(
    reader: ReservationReader,
    authority_reader: PartyAuthorityReader,
    *,
    organization_id: UUID,
    principal_id: UUID,
    reservation_id: UUID,
    allow_subject_override: bool = False,
) -> Reservation | None:
    reservation = await reader.get_reservation(organization_id, reservation_id)
    if reservation is None:
        return None
    if allow_subject_override:
        return reservation

    grant = await authority_reader.resolve_current(
        organization_id=organization_id,
        principal_id=principal_id,
        represented_party_id=reservation.subject_party_id,
        scope_key=MANAGE_APPOINTMENT_SCOPE,
    )
    if grant is None:
        raise SubjectAuthorityRequired(
            reservation.subject_party_id,
            MANAGE_APPOINTMENT_SCOPE,
        )
    return reservation
