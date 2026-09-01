import json

import pytest

from request_engine.modules.communications.application.errors import DeliveryConfigurationError
from request_engine.modules.communications.domain.delivery_policy import (
    PATIENT_TRANSACTIONAL_CONTACT_CHANNELS,
    parse_delivery_policy,
    patient_transactional_channel_policy,
    resolve_provider_key,
)


def test_delivery_policy_preserves_route_order_and_phone_endpoint_mapping() -> None:
    policy = parse_delivery_policy(
        {
            "channels": ["whatsapp", "sms"],
            "provider_key": "n8n",
            "reconcile_after_seconds": 120,
            "retry_after_seconds": 90,
        }
    )

    assert [route.channel for route in policy.routes] == ["whatsapp", "sms"]
    assert [route.endpoint_channel for route in policy.routes] == ["whatsapp", "phone"]
    assert all(route.provider_key == "n8n" for route in policy.routes)
    assert policy.reconcile_after_seconds == 120
    assert policy.retry_after_seconds == 90


def test_delivery_policy_rejects_unknown_channels_and_unbounded_delays() -> None:
    with pytest.raises(DeliveryConfigurationError, match="unsupported channel"):
        parse_delivery_policy(
            {
                "channels": ["carrier_pigeon"],
                "provider_key": "provider",
            }
        )

    with pytest.raises(DeliveryConfigurationError, match="retry_after_seconds"):
        parse_delivery_policy(
            {
                "channels": ["email"],
                "provider_key": "provider",
                "retry_after_seconds": 1,
            }
        )


def test_delivery_policy_without_provider_key_parses_and_rejects_empty_channels() -> None:
    policy = parse_delivery_policy({"channels": ["sms", "email"]})

    assert [route.provider_key for route in policy.routes] == [None, None]

    with pytest.raises(DeliveryConfigurationError, match="channels must be a non-empty list"):
        parse_delivery_policy({"channels": []})
    with pytest.raises(DeliveryConfigurationError, match="channels must be a non-empty list"):
        parse_delivery_policy({})


def test_provider_resolution_prefers_explicit_key_and_falls_back_to_single_provider() -> None:
    assert resolve_provider_key("explicit", ["other", "another"]) == "explicit"
    assert resolve_provider_key(None, ["provider-a"]) == "provider-a"


def test_provider_resolution_without_explicit_key_needs_exactly_one_provider() -> None:
    with pytest.raises(DeliveryConfigurationError, match="no delivery provider is configured"):
        resolve_provider_key(None, ())
    with pytest.raises(DeliveryConfigurationError, match="multiple delivery providers"):
        resolve_provider_key(None, ("provider-a", "provider-b"))


def test_patient_transactional_producer_policies_are_parseable_without_provider_key() -> None:
    policy = parse_delivery_policy(patient_transactional_channel_policy())

    assert [route.channel for route in policy.routes] == list(
        PATIENT_TRANSACTIONAL_CONTACT_CHANNELS
    )
    assert all(route.provider_key is None for route in policy.routes)
    slot_offer_payload = json.loads(json.dumps(patient_transactional_channel_policy()))
    assert parse_delivery_policy(slot_offer_payload) == policy
