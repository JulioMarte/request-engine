from typing import Protocol
from uuid import UUID


class BusinessPartyReader(Protocol):
    """Publish the tenancy-owned business-Party readiness fact."""

    async def has_active_organization_party(self, *, organization_id: UUID) -> bool: ...
