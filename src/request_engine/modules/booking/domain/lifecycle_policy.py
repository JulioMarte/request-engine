from dataclasses import dataclass
from typing import Literal, cast

from request_engine.modules.booking.domain.errors import BookingConfigurationError


@dataclass(frozen=True, slots=True)
class AttendancePolicy:
    confirmation_required: bool
    attendance_request_before_minutes: int | None
    decline_action: Literal["keep", "cancel"]
    no_response_action: Literal["keep"]
    no_show_after_minutes: int | None


@dataclass(frozen=True, slots=True)
class CommunicationsPolicy:
    confirmation: bool
    reminders_before_minutes: tuple[int, ...]
    channel_policy: dict[str, object]


@dataclass(frozen=True, slots=True)
class SlotRecoveryPolicy:
    enabled: bool
    minimum_lead_minutes: int


@dataclass(frozen=True, slots=True)
class ReservationLifecyclePolicy:
    attendance: AttendancePolicy
    communications: CommunicationsPolicy
    slot_recovery: SlotRecoveryPolicy


def reservation_lifecycle_policy(policy: dict[str, object]) -> ReservationLifecyclePolicy:
    attendance_raw = _object(policy.get("attendance"), "booking_policy.attendance")
    communications_raw = _object(
        policy.get("communications"), "booking_policy.communications"
    )
    recovery_raw = _object(policy.get("slot_recovery"), "booking_policy.slot_recovery")

    decline_action = attendance_raw.get("decline_action", "keep")
    if decline_action not in {"keep", "cancel"}:
        raise BookingConfigurationError(
            "booking_policy.attendance.decline_action must be keep or cancel"
        )
    no_response_action = attendance_raw.get("no_response_action", "keep")
    if no_response_action != "keep":
        raise BookingConfigurationError(
            "booking_policy.attendance.no_response_action supports only keep in V3 baseline"
        )

    reminders_raw = communications_raw.get("reminders_before_minutes", [])
    if not isinstance(reminders_raw, list):
        raise BookingConfigurationError(
            "booking_policy.communications.reminders_before_minutes must be a list"
        )
    reminders = tuple(
        sorted(
            {
                _positive_int(value, "booking_policy.communications.reminders_before_minutes")
                for value in cast(list[object], reminders_raw)
            },
            reverse=True,
        )
    )
    channel_policy = _object(
        communications_raw.get("channel_policy"),
        "booking_policy.communications.channel_policy",
    )

    return ReservationLifecyclePolicy(
        attendance=AttendancePolicy(
            confirmation_required=_boolean(
                attendance_raw.get("confirmation_required", False),
                "booking_policy.attendance.confirmation_required",
            ),
            attendance_request_before_minutes=_optional_positive_int(
                attendance_raw.get("attendance_request_before_minutes"),
                "booking_policy.attendance.attendance_request_before_minutes",
            ),
            decline_action=cast(Literal["keep", "cancel"], decline_action),
            no_response_action="keep",
            no_show_after_minutes=_optional_positive_int(
                attendance_raw.get("no_show_after_minutes"),
                "booking_policy.attendance.no_show_after_minutes",
            ),
        ),
        communications=CommunicationsPolicy(
            confirmation=_boolean(
                communications_raw.get("confirmation", False),
                "booking_policy.communications.confirmation",
            ),
            reminders_before_minutes=reminders,
            channel_policy=channel_policy,
        ),
        slot_recovery=SlotRecoveryPolicy(
            enabled=_boolean(
                recovery_raw.get("enabled", False),
                "booking_policy.slot_recovery.enabled",
            ),
            minimum_lead_minutes=_positive_int(
                recovery_raw.get("minimum_lead_minutes", 30),
                "booking_policy.slot_recovery.minimum_lead_minutes",
            ),
        ),
    )


def _object(value: object, field: str) -> dict[str, object]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise BookingConfigurationError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise BookingConfigurationError(f"{field} must be a boolean")
    return value


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise BookingConfigurationError(f"{field} must contain positive integers")
    return value


def _optional_positive_int(value: object, field: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, field)
