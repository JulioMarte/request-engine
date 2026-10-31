"""Read saved Location hours exceptions with ids under exact profile authority."""

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.catalog.application.queries.location_hours_exceptions import (
    LocationHoursExceptionItem,
    LocationHoursExceptionPage,
    LocationHoursExceptionQuery,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.db.tenant_principal_authority_reader import (
    require_current_tenant_capability,
)
from request_engine.platform.security.operational_authority import (
    MANAGE_OPERATIONAL_PROFILE_SCOPE,
    require_principal_serialized_operational_authority,
)


class PostgresLocationExceptionReader:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def location_hours_exceptions(
        self, query: LocationHoursExceptionQuery
    ) -> LocationHoursExceptionPage | None:
        if not 1 <= query.limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        async with tenant_transaction(self._session_factory, query.organization_id) as session:
            await require_current_tenant_capability(
                session,
                organization_id=query.organization_id,
                principal_id=query.principal_id,
                capability="catalog.read_configuration",
            )
            await require_principal_serialized_operational_authority(
                session,
                organization_id=query.organization_id,
                principal_id=query.principal_id,
                authority_party_id=query.authority_party_id,
                scope_key=MANAGE_OPERATIONAL_PROFILE_SCOPE,
            )
            revision = (
                await session.execute(
                    text(
                        """
                        SELECT operational_revision
                        FROM request_engine.locations
                        WHERE organization_id = :org AND id = :location_id
                        """
                    ),
                    {"org": query.organization_id, "location_id": query.location_id},
                )
            ).scalar_one_or_none()
            if revision is None:
                return None
            rows = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT id AS exception_id, location_id,
                                   lower(during) AS start_at, upper(during) AS end_at,
                                   exception_kind, reason, active, created_at, updated_at
                            FROM request_engine.location_hours_exceptions
                            WHERE organization_id = :org
                              AND location_id = :location_id
                              AND (:include_inactive OR active)
                              AND (CAST(:after AS uuid) IS NULL OR id > :after)
                            ORDER BY id
                            LIMIT :fetch_limit
                            """
                        ),
                        {
                            "org": query.organization_id,
                            "location_id": query.location_id,
                            "include_inactive": query.include_inactive,
                            "after": query.after,
                            "fetch_limit": query.limit + 1,
                        },
                    )
                )
                .mappings()
                .all()
            )
        return LocationHoursExceptionPage(
            operational_revision=cast(int, revision),
            items=tuple(
                LocationHoursExceptionItem(
                    exception_id=cast(UUID, row["exception_id"]),
                    location_id=cast(UUID, row["location_id"]),
                    start_at=cast(datetime, row["start_at"]),
                    end_at=cast(datetime, row["end_at"]),
                    exception_kind=(
                        "available" if row["exception_kind"] == "available" else "unavailable"
                    ),
                    reason=cast(str | None, row["reason"]),
                    active=cast(bool, row["active"]),
                    created_at=cast(datetime, row["created_at"]),
                    updated_at=cast(datetime, row["updated_at"]),
                )
                for row in rows
            ),
        )
