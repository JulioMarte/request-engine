from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID


class DelegationResolutionError(RuntimeError):
    """Base class for typed delegated-authority resolution failures."""


class DelegationInvalid(DelegationResolutionError):
    pass


class DelegationForeign(DelegationInvalid):
    pass


class DelegationNotCurrent(DelegationInvalid):
    pass


class DelegationStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


@dataclass(frozen=True, slots=True)
class DelegationSnapshot:
    delegation_id: UUID
    organization_id: UUID
    delegator_principal_id: UUID
    delegate_principal_id: UUID
    allowed_capabilities: frozenset[str]
    status: DelegationStatus
    not_before: datetime
    expires_at: datetime


class DelegationReader(Protocol):
    """Tenant-scoped reads; implementations must not cross organizations."""

    async def read_delegation(
        self, *, organization_id: UUID, delegation_id: UUID
    ) -> DelegationSnapshot | None: ...

    async def read_delegator_delegable_capabilities(
        self, *, organization_id: UUID, principal_id: UUID
    ) -> frozenset[str]: ...


def resolve_delegated_capabilities(
    *,
    delegation: DelegationSnapshot,
    delegator_delegable: frozenset[str],
    now: datetime,
) -> frozenset[str]:
    """Resolve delegated authority by intersection; never union authority sources.

    The delegated execution mode replaces the agent's standing authority with
    the intersection of the delegation grant and the delegator's current
    delegable authority. It must never be unioned with standing authority, and
    any failed precondition fails closed instead of falling back to standing
    authority. The AGENT Principal-kind ceiling (operational plane only) is
    already enforced where delegated capabilities are granted.
    """

    if delegation.status is not DelegationStatus.ACTIVE:
        raise DelegationNotCurrent("delegation is not active")
    if not (delegation.not_before <= now < delegation.expires_at):
        raise DelegationNotCurrent("delegation is outside its validity window")
    return delegation.allowed_capabilities & delegator_delegable
