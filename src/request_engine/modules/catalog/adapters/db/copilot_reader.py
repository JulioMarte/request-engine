from typing import cast
from uuid import UUID

from sqlalchemy import text

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
                    text(_RESOURCE_QUERY),
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
                    text(_OFFERING_QUERY),
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
                await session.execute(
                    text(_LOCATION_QUERY),
                    {"organization_id": organization_id, "location_id": location_id},
                )
            ).mappings().first()
            if row is None:
                return None
            return CopilotLocationClock(
                location_id=cast(UUID, row["location_id"]),
                timezone=cast(str, row["timezone"]),
                observed_at=row["observed_at"],
                operational_day_end_at=row["operational_day_end_at"],
                operational_revision=cast(int, row["operational_revision"]),
            )


def _resource_match(row: object) -> CopilotResourceMatch:
    values = cast(dict[str, object], row)
    return CopilotResourceMatch(
        resource_id=cast(UUID, values["resource_id"]),
        location_id=cast(UUID, values["location_id"]),
        assignment_id=cast(UUID, values["assignment_id"]),
        timezone=cast(str, values["timezone"]),
        observed_at=values["observed_at"],
        scheduled_end_at=values["scheduled_end_at"],
        location_operational_revision=cast(int, values["location_operational_revision"]),
        resource_availability_revision=cast(int, values["resource_availability_revision"]),
    )


_RESOURCE_QUERY = """
WITH clock AS (SELECT clock_timestamp() AS observed_at)
SELECT r.id AS resource_id, a.location_id, a.id AS assignment_id, l.timezone,
       clock.observed_at, l.operational_revision AS location_operational_revision,
       r.availability_revision AS resource_availability_revision,
       (((clock.observed_at AT TIME ZONE l.timezone)::date + max(rla.local_end))
         AT TIME ZONE l.timezone) AS scheduled_end_at
FROM request_engine.resources r
JOIN request_engine.resource_location_assignments a
  ON a.organization_id=r.organization_id AND a.resource_id=r.id
JOIN request_engine.locations l
  ON l.organization_id=a.organization_id AND l.id=a.location_id
CROSS JOIN clock
LEFT JOIN request_engine.resource_location_availability rla
  ON rla.organization_id=a.organization_id
 AND rla.resource_location_assignment_id=a.id
 AND rla.weekday=extract(isodow FROM clock.observed_at AT TIME ZONE l.timezone)::int - 1
WHERE r.organization_id=:organization_id AND a.effective_during @> clock.observed_at
  AND (lower(btrim(r.display_name))=lower(btrim(:reference))
       OR lower(btrim(r.resource_key))=lower(btrim(:reference)))
GROUP BY r.id,a.location_id,a.id,l.timezone,clock.observed_at,l.operational_revision,
         r.availability_revision
ORDER BY r.id,a.id
"""

_OFFERING_QUERY = """
SELECT id AS offering_id, display_name
FROM request_engine.offerings
WHERE organization_id=:organization_id
  AND (lower(btrim(display_name))=lower(btrim(:reference))
       OR lower(btrim(offering_key))=lower(btrim(:reference)))
ORDER BY id
"""

_LOCATION_QUERY = """
WITH clock AS (SELECT clock_timestamp() AS observed_at)
SELECT l.id AS location_id,l.timezone,clock.observed_at,l.operational_revision,
       (((clock.observed_at AT TIME ZONE l.timezone)::date + max(h.local_end))
         AT TIME ZONE l.timezone) AS operational_day_end_at
FROM request_engine.locations l
CROSS JOIN clock
LEFT JOIN request_engine.location_operational_hours h
  ON h.organization_id=l.organization_id AND h.location_id=l.id
 AND h.weekday=extract(isodow FROM clock.observed_at AT TIME ZONE l.timezone)::int - 1
WHERE l.organization_id=:organization_id AND l.id=:location_id
GROUP BY l.id,l.timezone,clock.observed_at,l.operational_revision
"""
