from datetime import datetime
from uuid import UUID

from request_engine.modules.booking.contracts.appointments import AppointmentSlot
from request_engine.modules.operational_recovery.contracts.models import RecoveryTarget


def choose_recovery_target(
    slots: tuple[AppointmentSlot, ...],
    *,
    original_start: datetime,
    original_end: datetime,
    source_contextual: bool,
) -> RecoveryTarget | None:
    """Choose a reschedule target without crossing commitment semantics."""

    candidates = tuple(
        slot for slot in slots if slot.start_at != original_start or slot.end_at != original_end
    )
    return _choose_compatible_target(candidates, source_contextual=source_contextual)


def choose_replacement_target(
    slots: tuple[AppointmentSlot, ...],
    *,
    original_start: datetime,
    original_end: datetime,
    source_resource_id: UUID,
    source_contextual: bool,
) -> RecoveryTarget | None:
    """Choose a same-time target that no longer depends on the degraded Resource."""

    candidates = tuple(
        slot
        for slot in slots
        if slot.start_at == original_start
        and slot.end_at == original_end
        and all(choice.resource_id != source_resource_id for choice in slot.resources)
    )
    return _choose_compatible_target(candidates, source_contextual=source_contextual)


def _choose_compatible_target(
    slots: tuple[AppointmentSlot, ...],
    *,
    source_contextual: bool,
) -> RecoveryTarget | None:
    blocked: RecoveryTarget | None = None
    for slot in slots:
        target_contextual = _slot_is_contextual(slot)
        if source_contextual == target_contextual:
            return _target_from_slot(slot, actionable=True, blocked_reason=None)
        if blocked is None:
            reason = (
                "contextual_source_requires_contextual_target"
                if source_contextual
                else "legacy_source_requires_legacy_target"
            )
            blocked = _target_from_slot(slot, actionable=False, blocked_reason=reason)
    return blocked


def _slot_is_contextual(slot: AppointmentSlot) -> bool:
    return any(choice.resource_location_assignment_id is not None for choice in slot.resources)


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
        planned_duration_minutes=slot.planned_duration_minutes,
        amount=slot.amount,
        currency=slot.currency,
        location_operational_revision=slot.location_operational_revision,
        configuration_fingerprint=slot.configuration_fingerprint,
    )
