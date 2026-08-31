from typing import cast
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.discovery.contracts.commands import DiscoveryPublicationState
from request_engine.modules.discovery.contracts.copilot import CopilotDiscoveryPublicationReader
from request_engine.platform.db.session import SessionFactory, tenant_transaction


class PostgresCopilotDiscoveryPublicationReader(CopilotDiscoveryPublicationReader):
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def get_publication(
        self,
        *,
        organization_id: UUID,
        publication_id: UUID,
    ) -> DiscoveryPublicationState | None:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            row = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT id, offering_id, location_id, resource_id,
                                   lower(effective_during) AS effective_start,
                                   upper(effective_during) AS effective_end,
                                   provider_visibility, status, revision
                            FROM request_engine.discovery_publications
                            WHERE organization_id=:organization_id AND id=:publication_id
                            """
                        ),
                        {
                            "organization_id": organization_id,
                            "publication_id": publication_id,
                        },
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            return DiscoveryPublicationState(
                id=cast(UUID, row["id"]),
                offering_id=cast(UUID, row["offering_id"]),
                location_id=cast(UUID, row["location_id"]),
                resource_id=cast(UUID | None, row["resource_id"]),
                effective_start=row["effective_start"],
                effective_end=row["effective_end"],
                provider_visibility=cast(str, row["provider_visibility"]),
                status=cast(str, row["status"]),
                revision=cast(int, row["revision"]),
            )
