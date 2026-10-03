"""Closed-purpose delivery intent for a staff invitation, not a Party contact."""

from collections.abc import Mapping
from datetime import datetime
from typing import Protocol
from uuid import UUID


class StaffInvitationDeliveryRecorder(Protocol):
    async def statuses(
        self,
        transaction: object,
        *,
        organization_id: UUID,
        generations: tuple[tuple[UUID, int], ...],
    ) -> Mapping[tuple[UUID, int], str]:
        """Read at most 101 exact tenant/invitation/generation states; omit missing rows."""
        ...

    async def status(
        self,
        transaction: object,
        *,
        organization_id: UUID,
        invitation_id: UUID,
        generation: int,
    ) -> str | None:
        """Read one generation's tenant-scoped delivery status, not its proof reference."""
        ...

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
    ) -> UUID:
        """Persist intent and dispatch action in the caller's transaction."""
        ...

    async def cancel(
        self,
        transaction: object,
        *,
        organization_id: UUID,
        invitation_id: UUID,
    ) -> None:
        """Fence unfinished generations atomically with owner lifecycle changes."""
        ...
