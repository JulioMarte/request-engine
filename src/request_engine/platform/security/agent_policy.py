from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.platform.security.operation_risk import OperationRiskClass


class AgentPolicyDenied(Exception):
    """Raised when an AGENT Principal has no admissible tool policy for an operation."""


class AgentRiskDenied(Exception):
    """Raised when an operation's risk class exceeds the agent policy ceiling."""


class AgentBudgetExceeded(Exception):
    """Raised when an agent exhausts its safety budget for the current window."""


@dataclass(frozen=True, slots=True)
class AgentPolicySnapshot:
    """Tenant-scoped tool/risk ceiling materialized fresh for one agent request."""

    allowed_capabilities: frozenset[str]
    denied_capabilities: frozenset[str]
    risk_ceiling: OperationRiskClass
    max_mutations_per_minute: int
    policy_revision: int


class AgentPolicyReader(Protocol):
    """Tenant-scoped reads; implementations must not cross organizations."""

    async def read_policy(
        self, *, organization_id: UUID, principal_id: UUID
    ) -> AgentPolicySnapshot | None: ...


class AgentBudgetEnforcer(Protocol):
    """Race-safe per-window mutation accounting for one agent principal."""

    async def consume_mutation(
        self, *, organization_id: UUID, principal_id: UUID, limit: int
    ) -> None: ...


__all__ = [
    "AgentBudgetEnforcer",
    "AgentBudgetExceeded",
    "AgentPolicyDenied",
    "AgentPolicyReader",
    "AgentPolicySnapshot",
    "AgentRiskDenied",
]
