from datetime import datetime
from uuid import UUID

from request_engine.modules.booking.contracts.appointments import AppointmentSlot
from request_engine.modules.operational_recovery.contracts.models import RecoveryTarget


def choose_recovery_target(
    slots: tuple[AppointmentSlot, ...],
    *,
    original_start: datetime,
    original_end: datetime,
) -> RecoveryTarget | None:
    """Choose the first current contextual reschedule target outside the original interval."""

    candidate = next(
        (
            slot
            for slot in slots
            if slot.start_at != original_start or slot.end_at != original_end
        ),
        None,
    )
    return _target_from_slot(candidate) if candidate is not None else None


def choose_replacement_target(
    slots: tuple[AppointmentSlot, ...],
    *,
    original_start: datetime,
    original_end: datetime,
    source_resource_id: UUID,
) -> RecoveryTarget | None:
    """Choose a same-time target that no longer depends on the degraded Resource."""

    candidate = next(
        (
            slot
            for slot in slots
            if slot.start_at == original_start
            and slot.end_at == original_end
            and all(choice.resource_id != source_resource_id for choice in slot.resources)
        ),
        None,
    )
    return _target_from_slot(candidate) if candidate is not None else None


def _target_from_slot(slot: AppointmentSlot) -> RecoveryTarget:
    return RecoveryTarget(
        start_at=slot.start_at,
        end_at=slot.end_at,
        location_id=slot.location_id,
        resources=slot.resources,
        actionable=True,
        blocked_reason=None,
        planned_duration_minutes=slot.planned_duration_minutes,
        amount=slot.amount,
        currency=slot.currency,
        location_operational_revision=slot.location_operational_revision,
        configuration_fingerprint=slot.configuration_fingerprint,
    )
