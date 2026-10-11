"""Bounded owner reads with current standing and exact Party authority."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.catalog.application.queries.administration import (
    AdministrativeLocation,
    AdministrativeOffering,
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
                            SELECT id AS location_id, location_key, display_name, timezone,
                                   active, operational_revision, address_line1, address_line2,
                                   locality, administrative_area, postal_code, country_code,
                                   latitude, longitude, geocoding_source, geocoded_at
                            FROM request_engine.locations
                            WHERE organization_id=:org
                              AND (CAST(:after AS uuid) IS NULL OR id>:after)
                              AND (CAST(:target AS uuid) IS NULL OR id=:target)
                            ORDER BY id LIMIT :fetch_limit
                        """),
                        self._params(query),
                    )
                )
                .mappings()
                .all()
            )
            return tuple(AdministrativeLocation(**row) for row in rows)

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
                                   COALESCE(p.revision,0) AS booking_policy_revision
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
