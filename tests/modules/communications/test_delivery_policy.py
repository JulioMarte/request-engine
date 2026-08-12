import pytest

from request_engine.modules.communications.application.errors import DeliveryConfigurationError
from request_engine.modules.communications.domain.delivery_policy import parse_delivery_policy


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
