from datetime import time
from typing import cast
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.booking.adapters.db.copilot_queries import (
    ASSIGNMENT_DAY_END_QUERY,
    RESOURCE_QUERY,
)
from request_engine.modules.booking.contracts.copilot import (
    CopilotBookingReader,
    CopilotResourceMatch,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction


class PostgresCopilotBookingReader(CopilotBookingReader):
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
            return tuple(
                CopilotResourceMatch(
                    resource_id=cast(UUID, row["resource_id"]),
                    location_id=cast(UUID, row["location_id"]),
                    assignment_id=cast(UUID, row["assignment_id"]),
                    resource_availability_revision=cast(int, row["resource_availability_revision"]),
                    display_name=cast(str, row["display_name"]),
                )
                for row in rows
            )

    async def read_assignment_day_end(
        self,
        *,
        organization_id: UUID,
        assignment_id: UUID,
        weekday: int,
    ) -> time | None:
        if weekday < 0 or weekday > 6:
            raise ValueError("weekday must be between 0 and 6")
        async with tenant_transaction(self._session_factory, organization_id) as session:
            value = (
                await session.execute(
                    text(ASSIGNMENT_DAY_END_QUERY),
                    {
                        "organization_id": organization_id,
                        "assignment_id": assignment_id,
                        "weekday": weekday,
                    },
                )
            ).scalar_one()
            return cast(time | None, value)
