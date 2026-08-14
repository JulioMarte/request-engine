import pytest

from request_engine.modules.booking.domain.errors import BookingConfigurationError
from request_engine.modules.booking.domain.lifecycle_policy import reservation_lifecycle_policy


def test_lifecycle_policy_defaults_to_no_automation() -> None:
    policy = reservation_lifecycle_policy({})

    assert policy.attendance.confirmation_required is False
    assert policy.attendance.decline_action == "keep"
    assert policy.attendance.no_response_action == "keep"
    assert policy.attendance.no_show_after_minutes is None
    assert policy.communications.confirmation is False
    assert policy.communications.reminders_before_minutes == ()
    assert policy.communications.channel_policy == {}
    assert policy.slot_recovery.enabled is False
    assert policy.slot_recovery.minimum_lead_minutes == 30


def test_lifecycle_policy_normalizes_supported_configuration() -> None:
    policy = reservation_lifecycle_policy(
        {
            "attendance": {
                "confirmation_required": True,
                "attendance_request_before_minutes": 1440,
                "decline_action": "cancel",
                "no_response_action": "keep",
                "no_show_after_minutes": 15,
            },
            "communications": {
                "confirmation": True,
                "reminders_before_minutes": [120, 1440, 120],
                "channel_policy": {
                    "channels": ["whatsapp", "sms"],
                    "provider_key": "provider",
                },
            },
            "slot_recovery": {"enabled": True, "minimum_lead_minutes": 45},
        }
    )

    assert policy.attendance.confirmation_required is True
    assert policy.attendance.attendance_request_before_minutes == 1440
    assert policy.attendance.decline_action == "cancel"
    assert policy.attendance.no_show_after_minutes == 15
    assert policy.communications.confirmation is True
    assert policy.communications.reminders_before_minutes == (1440, 120)
    assert policy.slot_recovery.enabled is True
    assert policy.slot_recovery.minimum_lead_minutes == 45


@pytest.mark.parametrize(
    "raw",
    [
        {"attendance": {"decline_action": "release"}},
        {"attendance": {"no_response_action": "cancel"}},
        {"attendance": {"no_show_after_minutes": 0}},
        {"communications": {"reminders_before_minutes": "120"}},
        {"communications": {"confirmation": "yes"}},
        {"slot_recovery": {"minimum_lead_minutes": False}},
    ],
)
def test_lifecycle_policy_rejects_unsupported_or_ambiguous_values(
    raw: dict[str, object],
) -> None:
    with pytest.raises(BookingConfigurationError):
        reservation_lifecycle_policy(raw)
