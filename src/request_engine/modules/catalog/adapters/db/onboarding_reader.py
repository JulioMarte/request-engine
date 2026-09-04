from uuid import UUID

from sqlalchemy import text

from request_engine.modules.catalog.contracts.onboarding import CatalogOnboardingSupply
from request_engine.platform.db.session import SessionFactory, tenant_transaction


class PostgresCatalogOnboardingReader:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def read_catalog_supply(self, *, organization_id: UUID) -> CatalogOnboardingSupply:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            location_count = (
                await session.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM request_engine.locations
                        WHERE organization_id = :organization_id AND active
                        """
                    ),
                    {"organization_id": organization_id},
                )
            ).scalar_one()
            bookable_count = (
                await session.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM request_engine.offering_versions
                        WHERE organization_id = :organization_id AND bookable
                        """
                    ),
                    {"organization_id": organization_id},
                )
            ).scalar_one()
            return CatalogOnboardingSupply(
                location_count=int(location_count),
                bookable_offering_version_count=int(bookable_count),
            )
