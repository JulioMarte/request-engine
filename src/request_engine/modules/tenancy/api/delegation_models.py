from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class CreateDelegationBody(BaseModel):
    delegate_principal_id: UUID
    purpose: str = Field(min_length=1, max_length=500)
    allowed_capabilities: list[str] = Field(min_length=1, max_length=64)
    not_before: datetime
    expires_at: datetime
    provenance_reference: str = Field(min_length=1, max_length=500)


class DelegationView(BaseModel):
    delegation_id: UUID
    revision: int
    status: str = "active"


class RevokeDelegationBody(BaseModel):
    expected_revision: int = Field(ge=1)
    provenance_reference: str = Field(min_length=1, max_length=500)


class DelegationRevisionView(BaseModel):
    delegation_revision: int
