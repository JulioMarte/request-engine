"""Published tenancy staff administrative contact surfaces (docs/v3/38 §9.2)."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class PrincipalContact:
    """One administrative contact of a staff principal."""

    contact_id: UUID
    channel: str
    normalized_value: str
    verified: bool
    active: bool


@dataclass(frozen=True, slots=True)
class PrincipalContactVerificationIssued:
    """One issued verification challenge: contact id and expiry, never the code."""

    contact_id: UUID
    expires_at: datetime
