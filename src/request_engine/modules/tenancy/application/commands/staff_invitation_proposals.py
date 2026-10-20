"""Agent-proposed, HUMAN-approved staff invitation intents (ADR 0019).

A proposal is an inert durable request for a HUMAN decision. Creating one grants,
sends and invites nothing. Approval reuses the ordinary staff invitation write path
under current HUMAN ``staff.invite`` authority; rejection closes the proposal.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

PROPOSAL_DISPLAY_NAME_MAX = 200
PROPOSAL_NOTE_MAX = 1000
PROPOSAL_REJECTION_REASON_MAX = 500


class StaffInvitationProposalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class ProposeStaffInvitationCommand:
    email: str
    provenance_reference: str
    idempotency_key: str
    display_name: str | None = None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class ApproveStaffInvitationProposalCommand:
    proposal_id: UUID
    expected_revision: int
    provenance_reference: str
    idempotency_key: str
    expires_in_hours: int = 72


@dataclass(frozen=True, slots=True)
class RejectStaffInvitationProposalCommand:
    proposal_id: UUID
    expected_revision: int
    provenance_reference: str
    idempotency_key: str
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class StaffInvitationProposal:
    proposal_id: UUID
    organization_id: UUID
    email: str
    display_name: str | None
    note: str | None
    status: str
    revision: int
    proposed_by_principal_id: UUID
    proposed_by_principal_kind: str
    proposed_by_display_name: str | None
    created_at: datetime
    decided_at: datetime | None
    decided_by_principal_id: UUID | None
    invitation_id: UUID | None
    rejection_reason: str | None


def optional_text(value: str | None, *, maximum: int) -> str | None:
    """Trim optional free text; blank means absent. Raises ValueError when too long."""

    if value is None:
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    if len(trimmed) > maximum:
        raise ValueError(f"text must contain at most {maximum} characters")
    return trimmed
