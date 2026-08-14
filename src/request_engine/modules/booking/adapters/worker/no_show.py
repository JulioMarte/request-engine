from uuid import UUID

from request_engine.modules.booking.application.commands.evaluate_no_show import (
    EvaluateNoShowCommand,
    EvaluateNoShowHandler,
    evaluate_no_show,
)
from request_engine.modules.booking.contracts.attendance import ReservationAttendanceState


async def handle_no_show_action(
    handler: EvaluateNoShowHandler,
    *,
    organization_id: UUID,
    worker_principal_id: UUID,
    reservation_id: UUID,
    lifecycle_key: str,
) -> ReservationAttendanceState:
    return await evaluate_no_show(
        handler,
        EvaluateNoShowCommand(
            organization_id=organization_id,
            principal_id=worker_principal_id,
            reservation_id=reservation_id,
            idempotency_key=f"scheduled:no-show:{reservation_id}:{lifecycle_key}",
        ),
    )
