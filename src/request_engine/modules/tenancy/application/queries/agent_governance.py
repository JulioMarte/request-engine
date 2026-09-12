from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.modules.tenancy.domain.agent_governance import (
    AgentOperatingMode,
    AgentProfileStatus,
)
from request_engine.platform.security.context import ActorContext


@dataclass(frozen=True, slots=True)
class AgentSummary:
    principal_id: UUID
    display_name: str
    purpose: str
    sponsor_principal_id: UUID
    operating_mode: AgentOperatingMode
    status: AgentProfileStatus
    principal_active: bool
    profile_revision: int
    authority_revision: int
    standing_capabilities: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ListAgentsQuery:
    after: UUID | None = None
    limit: int = 50


class AgentGovernanceReader(Protocol):
    async def list_agents(
        self, actor: ActorContext, query: ListAgentsQuery
    ) -> tuple[AgentSummary, ...]: ...

    async def read_agent(self, actor: ActorContext, principal_id: UUID) -> AgentSummary: ...
