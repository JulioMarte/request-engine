"""Tenancy-owned email invitation intents and subject acceptance receipts."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

InvitationDeliveryChannel = Literal["email", "link"]
"""How the acceptance proof of one generation reaches the invitee.

``email``: Communications delivers it asynchronously (governed secret store).
``link``: the inviter receives it exactly once in the create/resend response to
share through any channel; only its digest is persisted.
"""

_MAILBOX = re.compile(
    r"[a-z0-9_%+-]+(?:\.[a-z0-9_%+-]+)*@"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+"
)


def normalize_invitation_email(value: str) -> str:
    email = value.strip().lower()
    if not 3 <= len(email) <= 254 or _MAILBOX.fullmatch(email) is None:
        raise ValueError("Invalid email address")
    if len(email.partition("@")[0]) > 64:
        raise ValueError("Invalid email address")
    return email


class InvitationDeliveryIntent(Protocol):
    """Caller-owned port; composition supplies Communications' transactional recorder."""

    async def statuses(
        self,
        transaction: object,
        *,
        organization_id: UUID,
        generations: tuple[tuple[UUID, int], ...],
    ) -> Mapping[tuple[UUID, int], str]: ...

    async def record(
        self,
        transaction: object,
        *,
        organization_id: UUID,
        invitation_id: UUID,
        generation: int,
        destination_address: str,
        secret_reference: str,
        secret_digest: str,
        expires_at: datetime,
    ) -> UUID: ...

    async def cancel(
        self,
        transaction: object,
        *,
        organization_id: UUID,
        invitation_id: UUID,
    ) -> None: ...

    async def status(
        self,
        transaction: object,
        *,
        organization_id: UUID,
        invitation_id: UUID,
        generation: int,
    ) -> str | None: ...


@dataclass(frozen=True, slots=True)
class CreateStaffInvitationCommand:
    email: str
    provenance_reference: str
    idempotency_key: str
    expires_in_hours: int = 72
    delivery: InvitationDeliveryChannel = "email"


@dataclass(frozen=True, slots=True)
class ChangeStaffInvitationCommand:
    invitation_id: UUID
    expected_revision: int
    provenance_reference: str
    idempotency_key: str
    # Resend only: the channel of the new proof generation. Revoke ignores it.
    delivery: InvitationDeliveryChannel = "email"


@dataclass(frozen=True, slots=True)
class StaffInvitation:
    invitation_id: UUID
    organization_id: UUID
    email: str
    status: str
    generation: int
    revision: int
    expires_at: datetime
    created_at: datetime
    membership_id: UUID | None
    principal_id: UUID | None
    binding_id: UUID | None
    delivery_status: str | None
    delivery_channel: str = "email"
    # One-time shareable proof: present only in the response of the command that
    # issued a fresh ``link`` generation, never in reads or idempotent replays.
    acceptance_token: str | None = None
    acceptance_url: str | None = None
