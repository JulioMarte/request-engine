from datetime import datetime

from request_engine.modules.booking.contracts.appointments import AppointmentSlot
from request_engine.modules.operational_recovery.contracts.models import RecoveryTarget


def choose_recovery_target(
    slots: tuple[AppointmentSlot, ...],
    *,
    original_start: datetime,
    original_end: datetime,
    source_contextual: bool,
) -> RecoveryTarget | None:
    """Prefer a genuinely actionable target and fail closed for contextual reschedule."""

    blocked: RecoveryTarget | None = None
    for slot in slots:
        if slot.start_at == original_start and slot.end_at == original_end:
            continue
        target_contextual = any(
            choice.resource_location_assignment_id is not None for choice in slot.resources
        )
        if source_contextual:
            if blocked is None:
                blocked = _target_from_slot(
                    slot,
                    actionable=False,
                    blocked_reason="contextual_source_reschedule_not_supported",
                )
            continue
        if not target_contextual:
            return _target_from_slot(slot, actionable=True, blocked_reason=None)
        if blocked is None:
            blocked = _target_from_slot(
                slot,
                actionable=False,
                blocked_reason="contextual_target_reschedule_not_supported",
            )
    return blocked


def _target_from_slot(
    slot: AppointmentSlot,
    *,
    actionable: bool,
    blocked_reason: str | None,
) -> RecoveryTarget:
    return RecoveryTarget(
        start_at=slot.start_at,
        end_at=slot.end_at,
        location_id=slot.location_id,
        resources=slot.resources,
        actionable=actionable,
        blocked_reason=blocked_reason,
    )
