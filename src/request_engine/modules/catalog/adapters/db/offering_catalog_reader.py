from datetime import UTC, datetime
from decimal import Decimal
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.catalog.application.queries.search_offerings import (
    OfferingSummary,
    OfferingVersionInfo,
    SearchOfferingsQuery,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction

_LEGACY_SEARCH_SELECT = """
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

_F1_SEARCH_SELECT = """
SELECT o.id,
       o.offering_key,
       o.display_name,
       o.description,
       latest.id AS version_id,
       latest.version,
       latest.duration_minutes,
       latest.bookable,
       latest.requestable,
       latest.public_data,
       base_terms.amount,
       base_terms.currency
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
LEFT JOIN request_engine.offering_version_booking_terms AS base_terms
  ON base_terms.organization_id = o.organization_id
 AND base_terms.offering_version_id = latest.id
"""


class PostgresOfferingCatalogReader:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def search_offerings(
        self,
        query: SearchOfferingsQuery,
    ) -> tuple[OfferingSummary, ...]:
        async with tenant_transaction(self._session_factory, query.organization_id) as session:
            f1_available = await _f1_catalog_schema_available(session)
            if query.location_id is not None and not f1_available:
                return ()

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
            if query.location_id is not None:
                effective_at = query.effective_at or datetime.now(UTC)
                predicates.extend(
                    [
                        """
                        EXISTS (
                            SELECT 1
                            FROM request_engine.locations l
                            WHERE l.organization_id = o.organization_id
                              AND l.id = :location_id
                              AND l.active
                        )
                        """,
                        """
                        NOT EXISTS (
                            SELECT 1
                            FROM request_engine.offering_resource_requirements req
                            WHERE req.organization_id = o.organization_id
                              AND req.offering_version_id = latest.id
                              AND (
                                  SELECT count(DISTINCT r.id)
                                  FROM request_engine.resources r
                                  JOIN request_engine.resource_capability_assignments rca
                                    ON rca.organization_id = r.organization_id
                                   AND rca.resource_id = r.id
                                   AND rca.capability_id = req.capability_id
                                  JOIN request_engine.resource_location_assignments a
                                    ON a.organization_id = r.organization_id
                                   AND a.resource_id = r.id
                                   AND a.location_id = :location_id
                                   AND a.status = 'active'
                                   AND a.effective_during @> CAST(:effective_at AS timestamptz)
                                  WHERE r.organization_id = o.organization_id
                                    AND r.active
                              ) < req.quantity
                        )
                        """,
                    ]
                )
                parameters["location_id"] = query.location_id
                parameters["effective_at"] = effective_at.astimezone(UTC)

            statement = text(
                (_F1_SEARCH_SELECT if f1_available else _LEGACY_SEARCH_SELECT)
                + "WHERE "
                + "\n  AND ".join(predicates)
                + "\nORDER BY o.display_name, o.id\nLIMIT :limit"
            )
            rows = (await session.execute(statement, parameters)).mappings().all()
        return tuple(_offering_from_row(row, f1_available=f1_available) for row in rows)

    async def get_offering_by_key(
        self,
        organization_id: UUID,
        offering_key: str,
    ) -> OfferingSummary | None:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            f1_available = await _f1_catalog_schema_available(session)
            statement = text(
                (_F1_SEARCH_SELECT if f1_available else _LEGACY_SEARCH_SELECT)
                + """WHERE o.organization_id = :organization_id
  AND o.offering_key = :offering_key
  AND o.active
"""
            )
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
        return _offering_from_row(row, f1_available=f1_available) if row is not None else None


async def _f1_catalog_schema_available(session: AsyncSession) -> bool:
    return bool(
        (
            await session.execute(
                text(
                    """
                    SELECT to_regclass('request_engine.resource_location_assignments') IS NOT NULL
                       AND to_regclass('request_engine.offering_version_booking_terms') IS NOT NULL
                    """
                )
            )
        ).scalar_one()
    )


def _offering_from_row(row: RowMapping, *, f1_available: bool) -> OfferingSummary:
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
            amount=cast(Decimal | None, row["amount"]) if f1_available else None,
            currency=cast(str | None, row["currency"]) if f1_available else None,
        ),
    )
