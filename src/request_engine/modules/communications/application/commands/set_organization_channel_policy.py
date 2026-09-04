from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.modules.communications.domain.delivery_policy import (
    ORGANIZATION_CHANNEL_PURPOSES,
    parse_delivery_policy,
)


@dataclass(frozen=True, slots=True)
class OrganizationChannelPolicyInput:
    purpose: str
    enabled: bool
    channels: tuple[str, ...]
    provider_key: str | None = None
    reconcile_after_seconds: int = 300
    retry_after_seconds: int = 60


@dataclass(frozen=True, slots=True)
class SetOrganizationChannelPolicyCommand:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    policy: OrganizationChannelPolicyInput
    expected_revision: int
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class OrganizationChannelPolicyState:
    purpose: str
    enabled: bool
    channel_policy: dict[str, object]
    revision: int


class SetOrganizationChannelPolicyHandler(Protocol):
    async def set_organization_channel_policy(
        self, command: SetOrganizationChannelPolicyCommand
    ) -> OrganizationChannelPolicyState: ...


async def set_organization_channel_policy(
    handler: SetOrganizationChannelPolicyHandler,
    command: SetOrganizationChannelPolicyCommand,
) -> OrganizationChannelPolicyState:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if command.expected_revision < 0:
        raise ValueError("expected_revision must not be negative")
    policy = command.policy
    if policy.purpose not in ORGANIZATION_CHANNEL_PURPOSES:
        raise ValueError(f"unsupported communication purpose {policy.purpose}")
    parse_delivery_policy(
        {
            "channels": list(policy.channels),
            "provider_key": policy.provider_key,
            "reconcile_after_seconds": policy.reconcile_after_seconds,
            "retry_after_seconds": policy.retry_after_seconds,
        }
    )
    return await handler.set_organization_channel_policy(command)
