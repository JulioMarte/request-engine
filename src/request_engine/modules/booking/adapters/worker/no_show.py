from uuid import UUID

from request_engine.modules.booking.adapters.db.lifecycle_scheduling import (
    NO_SHOW_ACTION_TYPE,
    NO_SHOW_ACTION_VERSION,
)
from request_engine.modules.booking.application.commands.evaluate_no_show import (
    EvaluateNoShowCommand,
    EvaluateNoShowHandler,
    evaluate_no_show,
)
from request_engine.modules.booking.contracts.attendance import ReservationAttendanceState
from request_engine.platform.scheduling.postgres import ScheduledActionLease
from request_engine.platform.worker.runtime import PermanentWorkError


async def handle_no_show_action(
    handler: EvaluateNoShowHandler,
    *,
    organization_id: UUID,
    worker_principal_id: UUID,
    reservation_id: UUID,
    lifecycle_key: str,
    scheduled_action_id: UUID | None = None,
    scheduled_action_claim_token: UUID | None = None,
) -> ReservationAttendanceState:
    return await evaluate_no_show(
        handler,
        EvaluateNoShowCommand(
            organization_id=organization_id,
            principal_id=worker_principal_id,
            reservation_id=reservation_id,
            idempotency_key=f"scheduled:no-show:{reservation_id}:{lifecycle_key}",
            scheduled_action_id=scheduled_action_id,
            scheduled_action_claim_token=scheduled_action_claim_token,
        ),
    )


class NoShowScheduledHandler:
    """Validate one Booking ScheduledAction before invoking no-show authority."""

    def __init__(self, handler: EvaluateNoShowHandler, *, worker_principal_id: UUID) -> None:
        self._handler = handler
        self._worker_principal_id = worker_principal_id

    async def handle(self, lease: ScheduledActionLease) -> ReservationAttendanceState:
        if (
            lease.owner_module != "booking"
            or lease.action_type != NO_SHOW_ACTION_TYPE
            or lease.action_version != NO_SHOW_ACTION_VERSION
            or lease.subject_kind != "Reservation"
            or lease.subject_id is None
        ):
            raise PermanentWorkError("unsupported_booking_scheduled_action")

        raw_reservation_id = lease.payload.get("reservation_id")
        lifecycle_key = lease.payload.get("lifecycle_key")
        if not isinstance(raw_reservation_id, str) or not isinstance(lifecycle_key, str):
            raise PermanentWorkError("no_show_scheduled_action_payload_invalid")
        try:
            reservation_id = UUID(raw_reservation_id)
        except ValueError as exc:
            raise PermanentWorkError("no_show_scheduled_action_payload_invalid") from exc
        if reservation_id != lease.subject_id:
            raise PermanentWorkError("no_show_scheduled_action_payload_mismatch")

        return await handle_no_show_action(
            self._handler,
            organization_id=lease.organization_id,
            worker_principal_id=self._worker_principal_id,
            reservation_id=reservation_id,
            lifecycle_key=lifecycle_key,
            scheduled_action_id=lease.id,
            scheduled_action_claim_token=lease.claim_token,
        )
