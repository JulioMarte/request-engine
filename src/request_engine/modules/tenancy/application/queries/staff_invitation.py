"""Proof-bound advisory facts a recipient can review before joining."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class StaffInvitationPreview:
    invitation_id: UUID
    organization_id: UUID
    organization_display_name: str
    status: str
    expires_at: datetime
