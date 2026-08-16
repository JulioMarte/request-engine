from typing import Never

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.adapters.db.capacity_errors import (
    normalize_capacity_integrity_error,
)
from request_engine.modules.booking.adapters.db.commitment_commands import (
    PostgresBookingCommitmentCommands,
)
from request_engine.modules.booking.adapters.db.reservation_commands import (
    PostgresReservationCommands,
)
from request_engine.modules.booking.adapters.db.slot_offer_capacity import PostgresSlotOfferCapacity
from request_engine.modules.booking.application.commands.acquire_capacity_hold import (
    AcquireCapacityHoldCommand,
)
from request_engine.modules.booking.application.commands.book_appointment import (
    BookAppointmentCommand,
)
from request_engine.modules.booking.application.commands.cancel_reservation import (
    CancelReservationCommand,
)
from request_engine.modules.booking.application.commands.confirm_capacity_hold import (
    ConfirmCapacityHoldCommand,
)
from request_engine.modules.booking.application.commands.reschedule_reservation import (
    RescheduleReservationCommand,
)
from request_engine.modules.booking.contracts.appointments import Reservation
from request_engine.modules.booking.contracts.holds import CapacityHold
from request_engine.modules.booking.contracts.slot_offer_capacity import (
    AcquireSlotOfferHold,
    ConsumeSlotOfferHold,
    ReleaseSlotOfferHold,
    SlotOfferCapacityUnavailable,
)
from request_engine.platform.db.session import SessionFactory


class CapacitySafeReservationCommands:
    """Reservation command adapter with the public capacity-conflict contract."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._delegate = PostgresReservationCommands(session_factory)

    async def book_appointment(self, command: BookAppointmentCommand) -> Reservation:
        try:
            return await self._delegate.book_appointment(command)
        except IntegrityError as exc:
            normalize_capacity_integrity_error(exc)

    async def cancel_reservation(self, command: CancelReservationCommand) -> Reservation:
        try:
            return await self._delegate.cancel_reservation(command)
        except IntegrityError as exc:
            normalize_capacity_integrity_error(exc)


class CapacitySafeBookingCommitmentCommands:
    """Hold/reschedule adapter with the same opaque capacity-conflict contract."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._delegate = PostgresBookingCommitmentCommands(session_factory)

    async def acquire_capacity_hold(self, command: AcquireCapacityHoldCommand) -> CapacityHold:
        try:
            return await self._delegate.acquire_capacity_hold(command)
        except IntegrityError as exc:
            normalize_capacity_integrity_error(exc)

    async def confirm_capacity_hold(self, command: ConfirmCapacityHoldCommand) -> Reservation:
        try:
            return await self._delegate.confirm_capacity_hold(command)
        except IntegrityError as exc:
            normalize_capacity_integrity_error(exc)

    async def reschedule_reservation(self, command: RescheduleReservationCommand) -> Reservation:
        try:
            return await self._delegate.reschedule_reservation(command)
        except IntegrityError as exc:
            normalize_capacity_integrity_error(exc)


class CapacitySafeSlotOfferCapacity:
    """Queue-facing capacity adapter that preserves the SlotOffer port contract."""

    def __init__(self) -> None:
        self._delegate = PostgresSlotOfferCapacity()

    async def acquire_slot_offer_hold(
        self,
        transaction: object,
        request: AcquireSlotOfferHold,
    ) -> CapacityHold:
        session = _async_session(transaction)
        try:
            # Queue owns the surrounding transaction and intentionally handles
            # capacity loss by closing the SlotOpportunity. PostgreSQL marks a
            # transaction failed after the shared-capacity trigger raises
            # 23P01, so isolate this speculative Hold acquisition in a savepoint
            # before translating the error into the Queue-facing port contract.
            async with session.begin_nested():
                return await self._delegate.acquire_slot_offer_hold(session, request)
        except IntegrityError as exc:
            _raise_slot_offer_capacity_unavailable(exc)

    async def consume_slot_offer_hold(
        self,
        transaction: object,
        request: ConsumeSlotOfferHold,
    ) -> Reservation:
        try:
            return await self._delegate.consume_slot_offer_hold(transaction, request)
        except IntegrityError as exc:
            _raise_slot_offer_capacity_unavailable(exc)

    async def release_slot_offer_hold(
        self,
        transaction: object,
        request: ReleaseSlotOfferHold,
    ) -> CapacityHold:
        try:
            return await self._delegate.release_slot_offer_hold(transaction, request)
        except IntegrityError as exc:
            _raise_slot_offer_capacity_unavailable(exc)


def _async_session(transaction: object) -> AsyncSession:
    if not isinstance(transaction, AsyncSession):
        raise TypeError("slot-offer capacity transaction must be an AsyncSession")
    return transaction


def _raise_slot_offer_capacity_unavailable(exc: IntegrityError) -> Never:
    sqlstate = getattr(exc.orig, "sqlstate", None)
    if sqlstate == "23P01":
        raise SlotOfferCapacityUnavailable("capacity unavailable") from None
    raise exc
