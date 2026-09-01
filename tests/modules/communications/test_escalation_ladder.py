"""DB-free escalation step proofs: vocabulary, ladder arithmetic, guards.

The PostgreSQL behavior of the step is proven in
tests/integration/v3_worker_runtime/test_escalation_step*.py; this module pins
the closed trigger vocabulary, the deterministic escalation identity, the
next-channel walk arithmetic and the guard interpretation.
"""

from uuid import UUID

import pytest

from request_engine.modules.communications.adapters.db.escalation_ladder import (
    escalation_dedupe_key,
)
from request_engine.modules.communications.domain.delivery_policy import (
    parse_delivery_policy,
)
from request_engine.modules.communications.domain.errors import DeliveryConfigurationError
from request_engine.modules.communications.domain.escalation_policy import (
    DEFAULT_MAX_CONTACTS_PER_SUBJECT_PER_DAY,
    DEFAULT_MAX_ESCALATIONS_PER_TASK,
    EscalationGuards,
    fatigue_limited,
    parse_escalation_guards,
    remaining_escalation_channels,
    validate_escalation_trigger,
)


def test_escalation_trigger_vocabulary_is_closed() -> None:
    assert validate_escalation_trigger("delivery_deadline_missed") == "delivery_deadline_missed"
    assert validate_escalation_trigger("definitive_failure") == "definitive_failure"
    assert validate_escalation_trigger("recipient_unreachable") == "recipient_unreachable"


def test_unknown_escalation_trigger_is_rejected() -> None:
    with pytest.raises(DeliveryConfigurationError):
        validate_escalation_trigger("provider_slow")


def test_remaining_channels_walk_policy_order_after_the_failed_channel() -> None:
    channels = ("whatsapp", "sms", "email")

    assert remaining_escalation_channels(channels, set(), "whatsapp") == ("sms", "email")
    assert remaining_escalation_channels(channels, {"sms"}, "whatsapp") == ("email",)


def test_remaining_channels_skip_exhausted_channels_and_replayed_ones() -> None:
    channels = ("whatsapp", "sms", "email")
    attempted = {"whatsapp", "sms"}

    assert remaining_escalation_channels(channels, attempted, "whatsapp") == ("email",)
    assert remaining_escalation_channels(channels, {"whatsapp", "sms", "email"}, "sms") == ()


def test_remaining_channels_without_a_failed_channel_start_at_policy_head() -> None:
    channels = ("whatsapp", "sms", "email")

    assert remaining_escalation_channels(channels, set(), None) == channels
    assert remaining_escalation_channels(channels, {"email"}, None) == ("whatsapp", "sms")


def test_remaining_channels_treat_an_unknown_failed_channel_as_unattempted() -> None:
    channels = ("whatsapp", "sms")

    assert remaining_escalation_channels(channels, set(), "fax") == channels


def test_escalation_dedupe_key_is_deterministic_per_parent_channel_ordinal() -> None:
    parent = UUID("018f0000-0000-7000-8000-000000000001")

    assert escalation_dedupe_key(parent, "sms", 1) == (
        f"communication:escalation:{parent}:sms:1:v1"
    )
    assert escalation_dedupe_key(parent, "sms", 1) == escalation_dedupe_key(parent, "sms", 1)
    assert escalation_dedupe_key(parent, "sms", 2) != escalation_dedupe_key(parent, "email", 1)


def test_fatigue_guard_refuses_at_the_daily_limit() -> None:
    guards = EscalationGuards(
        max_escalations_per_task=DEFAULT_MAX_ESCALATIONS_PER_TASK,
        max_contacts_per_subject_per_day=3,
    )

    assert fatigue_limited(2, guards) is False
    assert fatigue_limited(3, guards) is True
    assert fatigue_limited(4, guards) is True


def test_default_guards_match_the_closed_policy_defaults() -> None:
    guards = parse_escalation_guards({"channels": ["whatsapp", "sms"]})

    assert guards.max_escalations_per_task == DEFAULT_MAX_ESCALATIONS_PER_TASK == 2
    assert guards.max_contacts_per_subject_per_day == DEFAULT_MAX_CONTACTS_PER_SUBJECT_PER_DAY == 5


def test_policy_routes_used_by_the_ladder_walk_preserve_channel_order() -> None:
    policy = parse_delivery_policy({"channels": ["whatsapp", "sms", "email"]})

    assert tuple(route.channel for route in policy.routes) == ("whatsapp", "sms", "email")
