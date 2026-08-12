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

_SEARCH_SELECT = """
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
"""


class PostgresOfferingCatalogReader:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def search_offerings(
        self,
        query: SearchOfferingsQuery,
    ) -> tuple[OfferingSummary, ...]:
        predicates = ["o.organization_id = :organization_id", "o.active"]
        parameters: dict[str, object] = {
            "organization_id": query.organization_id,
            "limit": query.limit,
        }

        if query.search_text is not None and (search_text := query.search_text.strip()):
            predicates.append(
                "("
                "o.offering_key ILIKE :search_pattern "
                "OR o.display_name ILIKE :search_pattern "
                "OR COALESCE(o.description, '') ILIKE :search_pattern"
                ")"
            )
            parameters["search_pattern"] = f"%{search_text}%"
        if query.bookable is not None:
            predicates.append("latest.bookable = :bookable")
            parameters["bookable"] = query.bookable
        if query.requestable is not None:
            predicates.append("latest.requestable = :requestable")
            parameters["requestable"] = query.requestable

        statement = text(
            _SEARCH_SELECT
            + "WHERE "
            + "\n  AND ".join(predicates)
            + "\nORDER BY o.display_name, o.id\nLIMIT :limit"
        )
        async with tenant_transaction(self._session_factory, query.organization_id) as session:
            rows = (await session.execute(statement, parameters)).mappings().all()
        return tuple(_offering_from_row(row) for row in rows)

    async def get_offering_by_key(
        self,
        organization_id: UUID,
        offering_key: str,
    ) -> OfferingSummary | None:
        statement = text(
            _SEARCH_SELECT
            + """WHERE o.organization_id = :organization_id
  AND o.offering_key = :offering_key
  AND o.active
"""
        )
        async with tenant_transaction(self._session_factory, organization_id) as session:
            row = (
                (
                    await session.execute(
                        statement,
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
