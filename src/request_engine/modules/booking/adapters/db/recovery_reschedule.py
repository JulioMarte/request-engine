from sqlalchemy.exc import IntegrityError

from request_engine.modules.booking.adapters.db.capacity_errors import normalize_capacity_integrity_error
from request_engine.modules.booking.adapters.db.recovery_reschedule_flow import execute_recovery_reschedule
from request_engine.modules.booking.application.errors import AppointmentUnavailable, InvalidResourceSelection, OfferingVersionNotBookable, OfferingVersionNotFound, ReservationNotReschedulable, ReservationRevisionConflict
from request_engine.modules.booking.contracts.appointments import Reservation
from request_engine.modules.booking.contracts.recovery import RecoveryBookingConflict, RecoveryRescheduleRequest, RecoveryTargetUnavailable
from request_engine.platform.db.session import SessionFactory


class PostgresGuardedRecoveryReschedule:
    """Booking-owned reschedule that atomically validates F5 source provenance."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def reschedule(self, request: RecoveryRescheduleRequest) -> Reservation:
        try:
            return await execute_recovery_reschedule(self._session_factory, request)
        except IntegrityError as exc:
            normalize_capacity_integrity_error(exc)
        except (ReservationRevisionConflict, ReservationNotReschedulable) as exc:
            raise RecoveryBookingConflict(str(exc)) from exc
        except (AppointmentUnavailable, InvalidResourceSelection, OfferingVersionNotFound, OfferingVersionNotBookable) as exc:
            raise RecoveryTargetUnavailable(str(exc)) from exc
