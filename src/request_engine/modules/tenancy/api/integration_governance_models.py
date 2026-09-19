from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class IntegrationProvisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    identity_authority_id: UUID
    credential_expires_at: AwareDatetime
    provenance_reference: str = Field(min_length=1, max_length=500)


class IntegrationProvisionView(BaseModel):
    """The workload token is returned exactly once and is never replayable."""

    principal_id: UUID
    workload_identity_id: UUID
    credential_id: UUID
    binding_id: UUID
    authority_revision: int
    status: str = "pending"
    workload_token: str | None = Field(repr=False)


class IntegrationAuthorityReplaceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_authority_revision: int = Field(ge=1)
    desired_capabilities: list[str] = Field(max_length=128)
    provenance_reference: str = Field(min_length=1, max_length=500)


class IntegrationAuthorityReplaceView(BaseModel):
    authority_revision: int


class IntegrationStatusTransitionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    target_status: Literal["active", "suspended", "revoked"]
    provenance_reference: str = Field(min_length=1, max_length=500)


class IntegrationStatusTransitionView(BaseModel):
    authority_revision: int


class IntegrationLifecycleBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    provenance_reference: str = Field(min_length=1, max_length=500)


class IntegrationCredentialRotateBody(IntegrationLifecycleBody):
    credential_expires_at: AwareDatetime


class IntegrationCredentialRotateView(BaseModel):
    credential_id: UUID
    authority_revision: int
    workload_token: str | None = Field(repr=False)


class IntegrationCredentialView(BaseModel):
    credential_id: UUID
    status: str
    expires_at: datetime
    created_at: datetime


class IntegrationView(BaseModel):
    principal_id: UUID
    authority_revision: int
    status: str
    binding_id: UUID | None
    workload_identity_id: UUID | None
    identity_authority_id: UUID | None
    capabilities: list[str]
    credentials: list[IntegrationCredentialView]
    provenance_complete: bool


class IntegrationListView(BaseModel):
    items: list[IntegrationView]
    next_after: UUID | None
