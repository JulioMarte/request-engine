"""Bounded owner reads with current standing and exact Party authority."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import date, time
from typing import Any, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.catalog.application.queries.administration import (
    AdministrativeHoursWindow,
    AdministrativeLocation,
    AdministrativeLocationConfiguration,
    AdministrativeOffering,
    AdministrativePublicContact,
    CatalogAdministrationQuery,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.db.tenant_principal_authority_reader import (
    require_current_tenant_capability,
)
from request_engine.platform.security.operational_authority import (
    MANAGE_COMMERCIAL_TERMS_SCOPE,
    MANAGE_OPERATIONAL_PROFILE_SCOPE,
    require_principal_serialized_operational_authority,
)


def _location(row: RowMapping, *, detail: bool) -> AdministrativeLocation:
    values = dict(row)
    windows = cast(list[dict[str, Any]], values.pop("hours_windows"))
    contacts = cast(list[dict[str, Any]], values.pop("public_contacts"))
    if not detail:
        return AdministrativeLocation(**values)
    return AdministrativeLocationConfiguration(
        **values,
        hours_windows=tuple(
            AdministrativeHoursWindow(
                weekday=window["weekday"],
                local_start=time.fromisoformat(window["local_start"]),
                local_end=time.fromisoformat(window["local_end"]),
                valid_from=date.fromisoformat(window["valid_from"])
                if window["valid_from"]
                else None,
                valid_until=date.fromisoformat(window["valid_until"])
                if window["valid_until"]
                else None,
            )
            for window in windows
        ),
        public_contacts=tuple(AdministrativePublicContact(**contact) for contact in contacts),
    )


class PostgresCatalogAdministrationReader:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    @asynccontextmanager
    async def _authorized(
        self, query: CatalogAdministrationQuery, scope: str
    ) -> AsyncGenerator[AsyncSession]:
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
                scope_key=scope,
            )
            yield session

    @staticmethod
    def _params(query: CatalogAdministrationQuery) -> dict[str, UUID | int | None]:
        return {
            "org": query.organization_id,
            "after": query.after,
            "target": query.target_id,
            "fetch_limit": query.limit + 1,
        }

    async def locations(
        self, query: CatalogAdministrationQuery
    ) -> tuple[AdministrativeLocation, ...]:
        async with self._authorized(query, MANAGE_OPERATIONAL_PROFILE_SCOPE) as session:
            rows = (
                (
                    await session.execute(
                        text("""
                            SELECT l.id AS location_id, l.location_key, l.display_name, l.timezone,
                                   l.active, l.operational_revision,
                                   l.address_line1, l.address_line2,
                                   l.locality, l.administrative_area, l.postal_code, l.country_code,
                                   l.latitude, l.longitude, l.geocoding_source, l.geocoded_at,
                                   CASE WHEN CAST(:target AS uuid) IS NOT NULL THEN COALESCE((
                                     SELECT jsonb_agg(jsonb_build_object(
                                       'weekday',h.weekday,'local_start',h.local_start,
                                       'local_end',h.local_end,'valid_from',h.valid_from,
                                       'valid_until',h.valid_until)
                                       ORDER BY h.weekday,h.local_start,h.local_end,
                                                h.valid_from NULLS FIRST,
                                                h.valid_until NULLS FIRST,h.id)
                                     FROM request_engine.location_operational_hours h
                                     WHERE h.organization_id=l.organization_id
                                       AND h.location_id=l.id
                                       AND h.active
                                   ),'[]'::jsonb) END AS hours_windows,
                                   CASE WHEN CAST(:target AS uuid) IS NOT NULL THEN COALESCE((
                                     SELECT jsonb_agg(jsonb_build_object(
                                       'channel',c.channel,'value',c.normalized_value,'label',c.label)
                                       ORDER BY c.channel,c.normalized_value,c.id)
                                     FROM request_engine.location_public_contact_endpoints c
                                     WHERE c.organization_id=l.organization_id
                                       AND c.location_id=l.id
                                       AND c.active AND c.is_public
                                   ),'[]'::jsonb) END AS public_contacts
                            FROM request_engine.locations l
                            WHERE l.organization_id=:org
                              AND (CAST(:after AS uuid) IS NULL OR l.id>:after)
                              AND (CAST(:target AS uuid) IS NULL OR l.id=:target)
                            ORDER BY l.id LIMIT :fetch_limit
                        """),
                        self._params(query),
                    )
                )
                .mappings()
                .all()
            )
            return tuple(_location(row, detail=query.target_id is not None) for row in rows)

    async def offerings(
        self, query: CatalogAdministrationQuery
    ) -> tuple[AdministrativeOffering, ...]:
        async with self._authorized(query, MANAGE_COMMERCIAL_TERMS_SCOPE) as session:
            rows = (
                (
                    await session.execute(
                        text("""
                            SELECT o.id AS offering_id, o.offering_key, o.display_name,
                                   o.description, o.active, v.id AS offering_version_id,
                                   v.version, v.duration_minutes, v.bookable, v.requestable,
                                   COALESCE(p.revision,0) AS booking_policy_revision,
                                   o.revision
                            FROM request_engine.offerings o
                            JOIN LATERAL (
                                SELECT id,version,duration_minutes,bookable,requestable
                                FROM request_engine.offering_versions
                                WHERE organization_id=o.organization_id AND offering_id=o.id
                                ORDER BY version DESC,id DESC LIMIT 1
                            ) v ON true
                            LEFT JOIN LATERAL (
                                SELECT revision
                                FROM request_engine.offering_version_booking_policies
                                WHERE organization_id=o.organization_id AND offering_version_id=v.id
                                ORDER BY revision DESC LIMIT 1
                            ) p ON true
                            WHERE o.organization_id=:org
                              AND (CAST(:after AS uuid) IS NULL OR o.id>:after)
                              AND (CAST(:target AS uuid) IS NULL OR o.id=:target)
                            ORDER BY o.id LIMIT :fetch_limit
                        """),
                        self._params(query),
                    )
                )
                .mappings()
                .all()
            )
            return tuple(AdministrativeOffering(**row) for row in rows)
