from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.modules.tenancy.domain.agent_policy import AgentPolicy
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.operation_risk import OperationRiskClass


@dataclass(frozen=True, slots=True)
class ReplaceAgentPolicyCommand:
    agent_principal_id: UUID
    allowed_capabilities: tuple[str, ...]
    denied_capabilities: tuple[str, ...]
    risk_ceiling: OperationRiskClass
    max_mutations_per_minute: int
    provenance_reference: str
    idempotency_key: str


class AgentPolicyCommands(Protocol):
    async def read_policy(
        self,
        actor: ActorContext,
        agent_principal_id: UUID,
    ) -> AgentPolicy: ...

    async def replace_policy(
        self,
        actor: ActorContext,
        command: ReplaceAgentPolicyCommand,
    ) -> int: ...
