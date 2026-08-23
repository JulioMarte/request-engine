from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.discovery.application.queries.search_supply import (
    DiscoveryCandidate,
    SearchPublishedSupplyQuery,
)
from request_engine.platform.db.session import SessionFactory


class PostgresDiscoveryCandidateReader:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def find_candidates(
        self,
        query: SearchPublishedSupplyQuery,
        *,
        scan_limit: int,
    ) -> tuple[DiscoveryCandidate, ...]:
        async with self._session_factory() as session, session.begin():
            rows = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT *
                            FROM request_engine.search_discovery_candidates_v2(
                                :classification_key,
                                :latitude,
                                :longitude,
                                :radius_meters,
                                :window_start,
                                :window_end,
                                :scan_limit
                            )
                            """
                        ),
                        {
                            "classification_key": query.service_classification_key,
                            "latitude": float(query.origin_latitude),
                            "longitude": float(query.origin_longitude),
                            "radius_meters": query.radius_meters,
                            "window_start": query.window_start,
                            "window_end": query.window_end,
                            "scan_limit": scan_limit,
                        },
                    )
                )
                .mappings()
                .all()
            )
        return tuple(_from_row(row) for row in rows)


def _from_row(row: object) -> DiscoveryCandidate:
    values = cast(dict[str, object], row)
    return DiscoveryCandidate(
        publication_id=cast(UUID, values["publication_id"]),
        publication_revision=cast(int, values["publication_revision"]),
        organization_id=cast(UUID, values["organization_id"]),
        organization_key=cast(str, values["organization_key"]),
        organization_display_name=cast(str, values["organization_display_name"]),
        offering_id=cast(UUID, values["offering_id"]),
        offering_key=cast(str, values["offering_key"]),
        offering_display_name=cast(str, values["offering_display_name"]),
        offering_version_id=cast(UUID, values["offering_version_id"]),
        location_id=cast(UUID, values["location_id"]),
        location_key=cast(str, values["location_key"]),
        location_display_name=cast(str, values["location_display_name"]),
        resource_id=cast(UUID | None, values["resource_id"]),
        provider_visibility=cast(str, values["provider_visibility"]),
        publication_start=cast(datetime, values["publication_start"]),
        publication_end=cast(datetime | None, values["publication_end"]),
        distance_meters=cast(float, values["distance_meters"]),
    )
