from typing import Protocol
from uuid import UUID

from request_engine.modules.discovery.contracts.commands import DiscoveryPublicationState


class CopilotDiscoveryPublicationReader(Protocol):
    async def get_publication(
        self,
        *,
        organization_id: UUID,
        publication_id: UUID,
    ) -> DiscoveryPublicationState | None: ...
