from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping

from request_engine.modules.catalog.application.queries.search_offerings import (
    OfferingSummary,
    OfferingVersionInfo,
    SearchOfferingsQuery,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction


class PostgresOfferingCatalogReader:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def search_offerings(
        self,
        query: SearchOfferingsQuery,
    ) -> tuple[OfferingSummary, ...]:
        search_pattern = (
            f"%{query.search_text.strip()}%"
            if query.search_text is not None and query.search_text.strip()
            else None
        )
        async with tenant_transaction(self._session_factory, query.organization_id) as session:
            rows = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT o.id,
                                   o.offering_key,
                                   o.display_name,
                                   o.description,
                                   latest.id AS version_id,
                                   latest.version,
                                   latest.duration_minutes,
                                   latest.bookable,
                                   latest.requestable,
                                   latest.public_data
                            FROM request_engine.offerings AS o
                            JOIN LATERAL (
                                SELECT ov.id,
                                       ov.version,
                                       ov.duration_minutes,
                                       ov.bookable,
                                       ov.requestable,
                                       ov.public_data
                                FROM request_engine.offering_versions AS ov
                                WHERE ov.organization_id = o.organization_id
                                  AND ov.offering_id = o.id
                                ORDER BY ov.version DESC
                                LIMIT 1
                            ) AS latest ON true
                            WHERE o.organization_id = :organization_id
                              AND o.active
                              AND (
                                  :search_pattern IS NULL
                                  OR o.offering_key ILIKE :search_pattern
                                  OR o.display_name ILIKE :search_pattern
                                  OR COALESCE(o.description, '') ILIKE :search_pattern
                              )
                              AND (:bookable IS NULL OR latest.bookable = :bookable)
                              AND (:requestable IS NULL OR latest.requestable = :requestable)
                            ORDER BY o.display_name, o.id
                            LIMIT :limit
                            """
                        ),
                        {
                            "organization_id": query.organization_id,
                            "search_pattern": search_pattern,
                            "bookable": query.bookable,
                            "requestable": query.requestable,
                            "limit": query.limit,
                        },
                    )
                )
                .mappings()
                .all()
            )
        return tuple(_offering_from_row(row) for row in rows)

    async def get_offering_by_key(
        self,
        organization_id: UUID,
        offering_key: str,
    ) -> OfferingSummary | None:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            row = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT o.id,
                                   o.offering_key,
                                   o.display_name,
                                   o.description,
                                   latest.id AS version_id,
                                   latest.version,
                                   latest.duration_minutes,
                                   latest.bookable,
                                   latest.requestable,
                                   latest.public_data
                            FROM request_engine.offerings AS o
                            JOIN LATERAL (
                                SELECT ov.id,
                                       ov.version,
                                       ov.duration_minutes,
                                       ov.bookable,
                                       ov.requestable,
                                       ov.public_data
                                FROM request_engine.offering_versions AS ov
                                WHERE ov.organization_id = o.organization_id
                                  AND ov.offering_id = o.id
                                ORDER BY ov.version DESC
                                LIMIT 1
                            ) AS latest ON true
                            WHERE o.organization_id = :organization_id
                              AND o.offering_key = :offering_key
                              AND o.active
                            """
                        ),
                        {
                            "organization_id": organization_id,
                            "offering_key": offering_key,
                        },
                    )
                )
                .mappings()
                .first()
            )
        return _offering_from_row(row) if row is not None else None


def _offering_from_row(row: RowMapping) -> OfferingSummary:
    return OfferingSummary(
        id=cast(UUID, row["id"]),
        offering_key=cast(str, row["offering_key"]),
        display_name=cast(str, row["display_name"]),
        description=cast(str | None, row["description"]),
        latest_version=OfferingVersionInfo(
            id=cast(UUID, row["version_id"]),
            version=cast(int, row["version"]),
            duration_minutes=cast(int | None, row["duration_minutes"]),
            bookable=cast(bool, row["bookable"]),
            requestable=cast(bool, row["requestable"]),
            public_data=cast(dict[str, object], row["public_data"]),
        ),
    )
