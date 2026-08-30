from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping

from request_engine.modules.catalog.adapters.db.copilot_queries import (
    LOCATION_QUERY,
    OFFERING_QUERY,
    RESOURCE_QUERY,
)
from request_engine.modules.catalog.contracts.copilot import (
    CopilotCatalogReader,
    CopilotLocationClock,
    CopilotOfferingMatch,
    CopilotResourceMatch,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction


class PostgresCopilotCatalogReader(CopilotCatalogReader):
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def find_resources(
        self,
        *,
        organization_id: UUID,
        reference: str,
    ) -> tuple[CopilotResourceMatch, ...]:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            rows = (
                await session.execute(
                    text(RESOURCE_QUERY),
                    {"organization_id": organization_id, "reference": reference.strip()},
                )
            ).mappings()
            return tuple(_resource_match(row) for row in rows)

    async def find_offerings(
        self,
        *,
        organization_id: UUID,
        reference: str,
    ) -> tuple[CopilotOfferingMatch, ...]:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            rows = (
                await session.execute(
                    text(OFFERING_QUERY),
                    {"organization_id": organization_id, "reference": reference.strip()},
                )
            ).mappings()
            return tuple(
                CopilotOfferingMatch(
                    offering_id=cast(UUID, row["offering_id"]),
                    display_name=cast(str, row["display_name"]),
                )
                for row in rows
            )

    async def read_location_clock(
        self,
        *,
        organization_id: UUID,
        location_id: UUID,
    ) -> CopilotLocationClock | None:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            row = (
                (
                    await session.execute(
                        text(LOCATION_QUERY),
                        {"organization_id": organization_id, "location_id": location_id},
                    )
                )
                .mappings()
                .first()
            )
            return _location_clock(row) if row is not None else None


def _resource_match(row: RowMapping) -> CopilotResourceMatch:
    return CopilotResourceMatch(
        resource_id=cast(UUID, row["resource_id"]),
        location_id=cast(UUID, row["location_id"]),
        assignment_id=cast(UUID, row["assignment_id"]),
        timezone=cast(str, row["timezone"]),
        observed_at=_datetime(row, "observed_at"),
        scheduled_end_at=_optional_datetime(row, "scheduled_end_at"),
        location_operational_revision=cast(int, row["location_operational_revision"]),
        resource_availability_revision=cast(int, row["resource_availability_revision"]),
    )


def _location_clock(row: RowMapping) -> CopilotLocationClock:
    return CopilotLocationClock(
        location_id=cast(UUID, row["location_id"]),
        timezone=cast(str, row["timezone"]),
        observed_at=_datetime(row, "observed_at"),
        operational_day_end_at=_optional_datetime(row, "operational_day_end_at"),
        operational_revision=cast(int, row["operational_revision"]),
    )


def _datetime(row: RowMapping, key: str) -> datetime:
    return cast(datetime, row[key])


def _optional_datetime(row: RowMapping, key: str) -> datetime | None:
    return cast(datetime | None, row[key])
