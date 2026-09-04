from uuid import UUID

from sqlalchemy import text

from request_engine.modules.communications.contracts.onboarding import (
    CommunicationsOnboardingSupply,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction


class PostgresCommunicationsOnboardingReader:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def read_communications_supply(
        self, *, organization_id: UUID
    ) -> CommunicationsOnboardingSupply:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            disabled_count = (
                await session.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM request_engine.organization_channel_policies
                        WHERE organization_id = :organization_id
                          AND enabled = false
                        """
                    ),
                    {"organization_id": organization_id},
                )
            ).scalar_one()
            return CommunicationsOnboardingSupply(disabled_purpose_count=int(disabled_count))
