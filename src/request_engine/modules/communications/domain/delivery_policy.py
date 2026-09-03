"""Transactional delivery policy parsing.

Tasks declare channels; deployments declare transports; binding happens at
dispatch. ``PATIENT_TRANSACTIONAL_CONTACT_CHANNELS`` is the named default
channel set for reaching a patient by any verified contact point.
"""

from collections.abc import Collection
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from request_engine.modules.communications.domain.errors import DeliveryConfigurationError

_ENDPOINT_CHANNELS = {
    "email": "email",
    "phone": "phone",
    "sms": "phone",
    "voice": "phone",
    "whatsapp": "whatsapp",
}

PATIENT_TRANSACTIONAL_CONTACT_CHANNELS = ("whatsapp", "sms", "email")


class ChannelPolicyPurpose(StrEnum):
    """Closed vocabulary of purposes the communications module creates today."""

    APPOINTMENT_CONFIRMATION = "appointment_confirmation"
    APPOINTMENT_REMINDER = "appointment_reminder"
    ATTENDANCE_CONFIRMATION_REQUEST = "attendance_confirmation_request"
    SLOT_OFFER_AVAILABLE = "slot_offer_available"
    OPERATIONAL_RECOVERY_IMPACT = "operational_recovery_impact"
    OPERATIONAL_RECOVERY_RESCHEDULED = "operational_recovery_rescheduled"


ORGANIZATION_CHANNEL_PURPOSES = frozenset(item.value for item in ChannelPolicyPurpose)


def patient_transactional_channel_policy() -> dict[str, object]:
    """Policy that reaches the patient by any verified contact point."""

    return {"channels": list(PATIENT_TRANSACTIONAL_CONTACT_CHANNELS)}


def is_patient_transactional_default(policy: object) -> bool:
    """True when a frozen task policy is exactly the hardcoded default sentinel.

    Tasks created without an explicit task-level channel policy (slot-offer and
    operational-recovery intents) freeze the default sentinel. Only such
    sentinel policies defer to an organization-level policy at dispatch.
    """

    if not isinstance(policy, dict):
        return False
    entries = cast(dict[str, object], policy)
    if set(entries) != {"channels"}:
        return False
    channels = entries["channels"]
    if not isinstance(channels, list):
        return False
    typed_channels = cast(list[object], channels)
    if not all(isinstance(item, str) for item in typed_channels):
        return False
    string_channels = cast(list[str], typed_channels)
    return sorted(string_channels) == sorted(PATIENT_TRANSACTIONAL_CONTACT_CHANNELS)


@dataclass(frozen=True, slots=True)
class DeliveryRoute:
    channel: str
    endpoint_channel: str
    provider_key: str | None


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
    if raw_provider_key is not None and (
        not isinstance(raw_provider_key, str) or not raw_provider_key
    ):
        raise DeliveryConfigurationError(
            "channel_policy.provider_key must be a non-empty string when present"
        )
    reconcile_after_seconds = _bounded_seconds(
        raw_reconcile,
        field="channel_policy.reconcile_after_seconds",
    )
    retry_after_seconds = _bounded_seconds(
        raw_retry,
        field="channel_policy.retry_after_seconds",
    )

    typed_channels = cast(list[object], raw_channels)
    routes: list[DeliveryRoute] = []
    seen: set[str] = set()
    for raw_channel in typed_channels:
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


def resolve_provider_key(
    policy_provider_key: str | None,
    configured_provider_keys: Collection[str],
) -> str:
    """Bind a policy to a transport: explicit key wins, single provider falls back."""

    if policy_provider_key is not None:
        return policy_provider_key
    configured = sorted(set(configured_provider_keys))
    if len(configured) == 1:
        return configured[0]
    if not configured:
        raise DeliveryConfigurationError(
            "channel_policy.provider_key is required because no delivery provider is configured"
        )
    raise DeliveryConfigurationError(
        "channel_policy.provider_key is required because multiple delivery providers are configured"
    )


def _bounded_seconds(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 30 or value > 86400:
        raise DeliveryConfigurationError(f"{field} must be between 30 and 86400")
    return value
