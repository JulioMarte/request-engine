from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from request_engine.platform.security.operation_risk import OperationRiskClass


class AgentPolicyView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_principal_id: UUID
    allowed_capabilities: list[str]
    denied_capabilities: list[str]
    risk_ceiling: OperationRiskClass
    max_mutations_per_minute: int
    policy_revision: int


class AgentPolicyReplaceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed_capabilities: list[str] = Field(max_length=128)
    denied_capabilities: list[str] = Field(max_length=128)
    risk_ceiling: str
    max_mutations_per_minute: int
    provenance_reference: str = Field(min_length=1, max_length=500)
