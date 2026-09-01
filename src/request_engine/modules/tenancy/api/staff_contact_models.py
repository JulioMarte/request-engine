"""Transport DTOs for the staff administrative contact HTTP surface.

Pydantic belongs here only; application commands and contracts stay
framework-free. The verification code is never part of any response view.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.tenancy.contracts.staff_contacts import (
    PrincipalContact,
    PrincipalContactVerificationIssued,
)


class StaffContactBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channel: str = Field(min_length=1, max_length=16)
    value: str = Field(min_length=1, max_length=256)


class StaffContactConfirmBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=6, max_length=6)


class StaffContactView(BaseModel):
    contact_id: UUID
    channel: str
    normalized_value: str
    verified: bool
    active: bool

    @classmethod
    def from_contract(cls, contact: PrincipalContact) -> "StaffContactView":
        return cls(
            contact_id=contact.contact_id,
            channel=contact.channel,
            normalized_value=contact.normalized_value,
            verified=contact.verified,
            active=contact.active,
        )


class StaffContactVerificationIssuedView(BaseModel):
    contact_id: UUID
    expires_at: datetime

    @classmethod
    def from_contract(
        cls, issued: PrincipalContactVerificationIssued
    ) -> "StaffContactVerificationIssuedView":
        return cls(contact_id=issued.contact_id, expires_at=issued.expires_at)
