from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol
from uuid import UUID

from request_engine.modules.tenancy.domain.agent_governance import (
    AgentOperatingMode,
    AgentProfileStatus,
)
from request_engine.platform.security.context import ActorContext


@dataclass(frozen=True, slots=True)
class ProvisionAgentCommand:
    identity_authority_id: UUID
    display_name: str
    purpose: str
    sponsor_principal_id: UUID
    operating_mode: AgentOperatingMode
    credential_expires_at: datetime
    provenance_reference: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class ProvisionAgentResult:
    principal_id: UUID
    workload_identity_id: UUID
    credential_id: UUID
    binding_id: UUID
    profile_revision: int
    authority_revision: int | None = None
    workload_token: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class ReplaceAgentAuthorityCommand:
    agent_principal_id: UUID
    expected_authority_revision: int
    desired_capabilities: tuple[str, ...]
    provenance_reference: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class TransitionAgentProfileCommand:
    agent_principal_id: UUID
    expected_revision: int
    target_status: AgentProfileStatus
    provenance_reference: str
    idempotency_key: str


class AgentGovernanceCommands(Protocol):
    async def provision_agent(
        self,
        actor: ActorContext,
        command: ProvisionAgentCommand,
    ) -> ProvisionAgentResult: ...

    async def replace_agent_authority(
        self,
        actor: ActorContext,
        command: ReplaceAgentAuthorityCommand,
    ) -> int: ...

    async def transition_agent_profile(
        self,
        actor: ActorContext,
        command: TransitionAgentProfileCommand,
    ) -> int: ...
