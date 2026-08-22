from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime, time
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.catalog.application.queries.get_business_info import (
    BusinessInfo,
    BusinessLocation,
    OperationalHoursException,
    OperationalHoursWindow,
    PublicContactEndpoint,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction


class PostgresBusinessInfoReader:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def get_business_info(self, organization_id: UUID) -> BusinessInfo:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            if not await _f1_business_schema_available(session):
                return await _read_v3_business_info(session, organization_id)
            return await _read_f1_business_info(session, organization_id)


async def _f1_business_schema_available(session: AsyncSession) -> bool:
    return cast(
        bool,
        (
            await session.execute(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM pg_catalog.pg_attribute a
                        JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
                        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                        WHERE n.nspname = 'request_engine'
                          AND c.relname = 'organizations'
                          AND a.attname = 'operational_status'
                          AND a.attnum > 0
                          AND NOT a.attisdropped
                    )
                    """
                )
            )
        ).scalar_one(),
    )


async def _read_v3_business_info(session: AsyncSession, organization_id: UUID) -> BusinessInfo:
    business_row = (
        (
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
        )
        .mappings()
        .one()
    )
    location_rows = (
        (
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
        )
        .mappings()
        .all()
    )
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


async def _read_f1_business_info(session: AsyncSession, organization_id: UUID) -> BusinessInfo:
    business_row = (
        (
            await session.execute(
                text(
                    """
                    SELECT id AS organization_id, organization_key, display_name,
                           public_profile, legal_name, default_timezone,
                           default_locale, default_currency, operational_status
                    FROM request_engine.organizations
                    WHERE id = :organization_id
                    """
                ),
                {"organization_id": organization_id},
            )
        )
        .mappings()
        .one()
    )
    organization_contact_rows = (
        (
            await session.execute(
                text(
                    """
                    SELECT channel, normalized_value, label
                    FROM request_engine.organization_public_contact_endpoints
                    WHERE organization_id = :organization_id
                      AND active
                      AND is_public
                    ORDER BY channel, normalized_value, id
                    """
                ),
                {"organization_id": organization_id},
            )
        )
        .mappings()
        .all()
    )
    location_rows = (
        (
            await session.execute(
                text(
                    """
                    SELECT id, location_key, display_name, timezone, public_data,
                           address_line1, address_line2, locality,
                           administrative_area, postal_code, country_code
                    FROM request_engine.locations
                    WHERE organization_id = :organization_id
                      AND active
                    ORDER BY display_name, id
                    """
                ),
                {"organization_id": organization_id},
            )
        )
        .mappings()
        .all()
    )
    location_ids = tuple(cast(UUID, row["id"]) for row in location_rows)

    location_contact_rows: Sequence[RowMapping] = ()
    hours_rows: Sequence[RowMapping] = ()
    exception_rows: Sequence[RowMapping] = ()
    if location_ids:
        location_contact_rows = (
            (
                await session.execute(
                    text(
                        """
                        SELECT location_id, channel, normalized_value, label
                        FROM request_engine.location_public_contact_endpoints
                        WHERE organization_id = :organization_id
                          AND location_id = ANY(CAST(:location_ids AS uuid[]))
                          AND active
                          AND is_public
                        ORDER BY location_id, channel, normalized_value, id
                        """
                    ),
                    {
                        "organization_id": organization_id,
                        "location_ids": [str(value) for value in location_ids],
                    },
                )
            )
            .mappings()
            .all()
        )
        hours_rows = (
            (
                await session.execute(
                    text(
                        """
                        SELECT location_id, weekday, local_start, local_end,
                               valid_from, valid_until
                        FROM request_engine.location_operational_hours
                        WHERE organization_id = :organization_id
                          AND location_id = ANY(CAST(:location_ids AS uuid[]))
                          AND active
                        ORDER BY location_id, weekday, local_start, id
                        """
                    ),
                    {
                        "organization_id": organization_id,
                        "location_ids": [str(value) for value in location_ids],
                    },
                )
            )
            .mappings()
            .all()
        )
        exception_rows = (
            (
                await session.execute(
                    text(
                        """
                        SELECT location_id, lower(during) AS start_at,
                               upper(during) AS end_at, exception_kind
                        FROM request_engine.location_hours_exceptions
                        WHERE organization_id = :organization_id
                          AND location_id = ANY(CAST(:location_ids AS uuid[]))
                          AND active
                          AND upper(during) > clock_timestamp()
                        ORDER BY location_id, lower(during), id
                        """
                    ),
                    {
                        "organization_id": organization_id,
                        "location_ids": [str(value) for value in location_ids],
                    },
                )
            )
            .mappings()
            .all()
        )

    contacts_by_location: dict[UUID, list[PublicContactEndpoint]] = defaultdict(list)
    for row in location_contact_rows:
        contacts_by_location[cast(UUID, row["location_id"])].append(
            PublicContactEndpoint(
                channel=cast(str, row["channel"]),
                value=cast(str, row["normalized_value"]),
                label=cast(str | None, row["label"]),
            )
        )

    hours_by_location: dict[UUID, list[OperationalHoursWindow]] = defaultdict(list)
    for row in hours_rows:
        hours_by_location[cast(UUID, row["location_id"])].append(
            OperationalHoursWindow(
                weekday=cast(int, row["weekday"]),
                local_start=cast(time, row["local_start"]),
                local_end=cast(time, row["local_end"]),
                valid_from=cast(date | None, row["valid_from"]),
                valid_until=cast(date | None, row["valid_until"]),
            )
        )

    exceptions_by_location: dict[UUID, list[OperationalHoursException]] = defaultdict(list)
    for row in exception_rows:
        exceptions_by_location[cast(UUID, row["location_id"])].append(
            OperationalHoursException(
                start_at=cast(datetime, row["start_at"]),
                end_at=cast(datetime, row["end_at"]),
                kind=cast(str, row["exception_kind"]),
            )
        )

    return BusinessInfo(
        organization_id=cast(UUID, business_row["organization_id"]),
        organization_key=cast(str, business_row["organization_key"]),
        display_name=cast(str, business_row["display_name"]),
        public_profile=cast(dict[str, object], business_row["public_profile"]),
        legal_name=cast(str | None, business_row["legal_name"]),
        default_timezone=cast(str | None, business_row["default_timezone"]),
        default_locale=cast(str | None, business_row["default_locale"]),
        default_currency=cast(str | None, business_row["default_currency"]),
        operational_status=cast(str, business_row["operational_status"]),
        contacts=tuple(
            PublicContactEndpoint(
                channel=cast(str, row["channel"]),
                value=cast(str, row["normalized_value"]),
                label=cast(str | None, row["label"]),
            )
            for row in organization_contact_rows
        ),
        locations=tuple(
            BusinessLocation(
                id=location_id,
                location_key=cast(str, row["location_key"]),
                display_name=cast(str, row["display_name"]),
                timezone=cast(str, row["timezone"]),
                public_data=cast(dict[str, object], row["public_data"]),
                address_line1=cast(str | None, row["address_line1"]),
                address_line2=cast(str | None, row["address_line2"]),
                locality=cast(str | None, row["locality"]),
                administrative_area=cast(str | None, row["administrative_area"]),
                postal_code=cast(str | None, row["postal_code"]),
                country_code=cast(str | None, row["country_code"]),
                contacts=tuple(contacts_by_location.get(location_id, ())),
                operational_hours=tuple(hours_by_location.get(location_id, ())),
                hours_exceptions=tuple(exceptions_by_location.get(location_id, ())),
            )
            for row in location_rows
            for location_id in (cast(UUID, row["id"]),)
        ),
    )
