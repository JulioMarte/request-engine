from dataclasses import dataclass

from request_engine.modules.communications.application.errors import DeliveryConfigurationError

_ENDPOINT_CHANNELS = {
    "email": "email",
    "phone": "phone",
    "sms": "phone",
    "voice": "phone",
    "whatsapp": "whatsapp",
}


@dataclass(frozen=True, slots=True)
class DeliveryRoute:
    channel: str
    endpoint_channel: str
    provider_key: str


@dataclass(frozen=True, slots=True)
class DeliveryPolicy:
    routes: tuple[DeliveryRoute, ...]
    reconcile_after_seconds: int
    retry_after_seconds: int


def parse_delivery_policy(value: dict[str, object]) -> DeliveryPolicy:
    """Parse the deliberately small V3 transactional-delivery policy surface."""

    raw_channels = value.get("channels")
    raw_provider_key = value.get("provider_key")
    raw_reconcile = value.get("reconcile_after_seconds", 300)
    raw_retry = value.get("retry_after_seconds", 60)

    if not isinstance(raw_channels, list) or not raw_channels:
        raise DeliveryConfigurationError("channel_policy.channels must be a non-empty list")
    if not isinstance(raw_provider_key, str) or not raw_provider_key:
        raise DeliveryConfigurationError("channel_policy.provider_key must be a non-empty string")
    reconcile_after_seconds = _bounded_seconds(
        raw_reconcile,
        field="channel_policy.reconcile_after_seconds",
    )
    retry_after_seconds = _bounded_seconds(
        raw_retry,
        field="channel_policy.retry_after_seconds",
    )

    routes: list[DeliveryRoute] = []
    seen: set[str] = set()
    for raw_channel in raw_channels:
        if not isinstance(raw_channel, str) or raw_channel not in _ENDPOINT_CHANNELS:
            raise DeliveryConfigurationError(
                "channel_policy.channels contains an unsupported channel"
            )
        if raw_channel in seen:
            raise DeliveryConfigurationError("channel_policy.channels must be unique")
        seen.add(raw_channel)
        routes.append(
            DeliveryRoute(
                channel=raw_channel,
                endpoint_channel=_ENDPOINT_CHANNELS[raw_channel],
                provider_key=raw_provider_key,
            )
        )

    return DeliveryPolicy(
        routes=tuple(routes),
        reconcile_after_seconds=reconcile_after_seconds,
        retry_after_seconds=retry_after_seconds,
    )


def _bounded_seconds(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 30 or value > 86400:
        raise DeliveryConfigurationError(f"{field} must be between 30 and 86400")
    return value
