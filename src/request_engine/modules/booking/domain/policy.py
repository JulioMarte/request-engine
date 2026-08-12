from request_engine.modules.booking.application.errors import BookingConfigurationError


def slot_step_minutes(policy: dict[str, object], duration_minutes: int) -> int:
    """Return the baseline slot-grid step; default to service duration."""

    raw = policy.get("slot_step_minutes", duration_minutes)
    if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
        raise BookingConfigurationError(
            "booking_policy.slot_step_minutes must be a positive integer"
        )
    return raw
