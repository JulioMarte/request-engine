from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.platform.security.capabilities import (
    CAPABILITIES,
    CapabilityDefinition,
    CapabilityExposure,
)
from request_engine.platform.security.context import ActorContext


class TenantCapabilityPolicy(Protocol):
    """Resolve which product capabilities are enabled for one tenant."""

    async def enabled_capabilities(self, organization_id: UUID) -> frozenset[str]: ...


class BaselineTenantCapabilityPolicy:
    """Enable the current public/operator V3 baseline for every tenant.

    Deployments with feature policy can replace this resolver without changing
    discovery or authorization semantics.
    """

    async def enabled_capabilities(self, organization_id: UUID) -> frozenset[str]:
        del organization_id
        return frozenset(item.key for item in CAPABILITIES if item.discoverable)


@dataclass(frozen=True, slots=True)
class CapabilityAvailability:
    definition: CapabilityDefinition
    product_supported: bool
    tenant_enabled: bool
    actor_granted: bool
    context_executable: None = None


def _visible_to_actor(definition: CapabilityDefinition, actor: ActorContext) -> bool:
    if definition.exposure is CapabilityExposure.INTERNAL:
        return False
    if definition.exposure is CapabilityExposure.OPERATOR:
        return actor.allows(definition.key)
    return True


async def discover_capabilities(
    actor: ActorContext,
    policy: TenantCapabilityPolicy,
) -> tuple[CapabilityAvailability, ...]:
    """Return discovery facts without pretending they are execution authority."""

    enabled = await policy.enabled_capabilities(actor.organization_id)
    return tuple(
        CapabilityAvailability(
            definition=definition,
            product_supported=True,
            tenant_enabled=definition.key in enabled,
            actor_granted=actor.allows(definition.key),
        )
        for definition in CAPABILITIES
        if _visible_to_actor(definition, actor)
    )
