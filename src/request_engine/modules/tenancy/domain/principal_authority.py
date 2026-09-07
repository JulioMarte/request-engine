from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class AuthorityAssignmentRejected(ValueError):
    """Requested authority exceeds an explicit provisioning/delegation ceiling."""


@dataclass(frozen=True, slots=True)
class ProvisioningAuthorityCeiling:
    """Two independent ceilings that bound authority assignable by a creator."""

    creator_delegable: frozenset[str]
    provisioning_policy: frozenset[str]

    @property
    def maximum_assignable(self) -> frozenset[str]:
        return self.creator_delegable & self.provisioning_policy

    def require_assignment(self, desired: frozenset[str]) -> None:
        unauthorized = desired - self.maximum_assignable
        if unauthorized:
            names = ", ".join(sorted(unauthorized))
            raise AuthorityAssignmentRejected(
                f"authority outside creator/policy ceiling: {names}"
            )


class DelegationStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


@dataclass(frozen=True, slots=True)
class DelegationGrant:
    """Immutable snapshot of one bounded Principal-to-Agent task delegation."""

    id: UUID
    organization_id: UUID
    delegator_principal_id: UUID
    delegate_principal_id: UUID
    allowed_capabilities: frozenset[str]
    not_before: datetime
    expires_at: datetime
    revision: int
    status: DelegationStatus = DelegationStatus.ACTIVE

    def __post_init__(self) -> None:
        if not self.allowed_capabilities:
            raise ValueError("delegation must allow at least one capability")
        if self.expires_at <= self.not_before:
            raise ValueError("delegation expires_at must be after not_before")
        if self.revision <= 0:
            raise ValueError("delegation revision must be positive")
        if self.delegator_principal_id == self.delegate_principal_id:
            raise ValueError("a Principal cannot delegate authority to itself")

    def is_current(self, now: datetime) -> bool:
        return self.status is DelegationStatus.ACTIVE and self.not_before <= now < self.expires_at


def effective_delegated_capabilities(
    *,
    grant: DelegationGrant,
    now: datetime,
    agent_policy_ceiling: frozenset[str],
    delegator_current_delegable: frozenset[str],
    current_tool_policy: frozenset[str],
    current_context_policy: frozenset[str],
) -> frozenset[str]:
    """Resolve delegated agent authority by intersection; never union authority sources."""

    if not grant.is_current(now):
        return frozenset()
    return (
        agent_policy_ceiling
        & grant.allowed_capabilities
        & delegator_current_delegable
        & current_tool_policy
        & current_context_policy
    )
