from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from request_engine.modules.tenancy.domain.agent_governance import AgentOperatingMode


class AgentProvisionBody(BaseModel):
    identity_authority_id: UUID
    display_name: str = Field(min_length=1, max_length=200)
    purpose: str = Field(min_length=1, max_length=2000)
    sponsor_principal_id: UUID
    operating_mode: AgentOperatingMode
    credential_expires_at: datetime
    provenance_reference: str = Field(min_length=1, max_length=500)


class AgentProvisionView(BaseModel):
    """The workload token is returned exactly once and is never replayable."""

    principal_id: UUID
    workload_identity_id: UUID
    credential_id: UUID
    binding_id: UUID
    profile_revision: int
    status: str = "pending"
    workload_token: str | None


class AgentAuthorityReplaceBody(BaseModel):
    expected_authority_revision: int = Field(ge=1)
    desired_capabilities: list[str] = Field(max_length=128)
    provenance_reference: str = Field(min_length=1, max_length=500)


class AgentAuthorityReplaceView(BaseModel):
    authority_revision: int


class AgentProfileTransitionBody(BaseModel):
    expected_revision: int = Field(ge=1)
    target_status: Literal["active", "suspended", "revoked"]
    provenance_reference: str = Field(min_length=1, max_length=500)


class AgentProfileTransitionView(BaseModel):
    profile_revision: int
