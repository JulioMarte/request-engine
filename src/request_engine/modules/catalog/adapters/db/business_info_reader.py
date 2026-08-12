from typing import cast
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.catalog.application.queries.get_business_info import (
    BusinessInfo,
    BusinessLocation,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction


class PostgresBusinessInfoReader:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def get_business_info(self, organization_id: UUID) -> BusinessInfo:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            business_row = (
                await session.execute(
                    text(
                        """
                        SELECT organization_id, organization_key, display_name, public_profile
                        FROM request_read.business_info_v1
                        WHERE organization_id = :organization_id
                        """
                    ),
                    {"organization_id": organization_id},
                )
            ).mappings().one()

            location_rows = (
                await session.execute(
                    text(
                        """
                        SELECT id, location_key, display_name, timezone, public_data
                        FROM request_read.locations_v1
                        WHERE organization_id = :organization_id
                          AND active
                        ORDER BY display_name, id
                        """
                    ),
                    {"organization_id": organization_id},
                )
            ).mappings().all()

        return BusinessInfo(
            organization_id=cast(UUID, business_row["organization_id"]),
            organization_key=cast(str, business_row["organization_key"]),
            display_name=cast(str, business_row["display_name"]),
            public_profile=cast(dict[str, object], business_row["public_profile"]),
            locations=tuple(
                BusinessLocation(
                    id=cast(UUID, row["id"]),
                    location_key=cast(str, row["location_key"]),
                    display_name=cast(str, row["display_name"]),
                    timezone=cast(str, row["timezone"]),
                    public_data=cast(dict[str, object], row["public_data"]),
                )
                for row in location_rows
            ),
        )
