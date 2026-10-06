from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.application.queries.supply_configuration import (
    AssignmentConfiguration,
    AvailabilityConfiguration,
    ExceptionConfiguration,
    ResourceConfiguration,
    SupplyConfigurationQuery,
    TermsConfiguration,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.db.tenant_principal_authority_reader import (
    require_current_tenant_capability,
)
from request_engine.platform.security.operational_authority import (
    MANAGE_COMMERCIAL_TERMS_SCOPE,
    MANAGE_CONTEXTUAL_SUPPLY_SCOPE,
    require_principal_serialized_operational_authority,
)


class PostgresSupplyConfigurationReader:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    @asynccontextmanager
    async def _authorized(
        self, query: SupplyConfigurationQuery, scope: str
    ) -> AsyncGenerator[AsyncSession]:
        if not 1 <= query.limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        async with tenant_transaction(self._session_factory, query.organization_id) as session:
            await require_current_tenant_capability(
                session,
                organization_id=query.organization_id,
                principal_id=query.principal_id,
                capability="booking.read_supply",
            )
            await require_principal_serialized_operational_authority(
                session,
                organization_id=query.organization_id,
                principal_id=query.principal_id,
                authority_party_id=query.authority_party_id,
                scope_key=scope,
            )
            yield session

    async def read_resources(
        self, query: SupplyConfigurationQuery
    ) -> tuple[ResourceConfiguration, ...]:
        async with self._authorized(query, MANAGE_CONTEXTUAL_SUPPLY_SCOPE) as session:
            rows = (
                (
                    await session.execute(
                        text("""
                SELECT r.id, r.resource_key, r.display_name, r.capacity_model, r.capacity_units,
                       r.active, r.availability_revision,
                       ARRAY(SELECT c.capability_id
                             FROM request_engine.resource_capability_assignments c
                             WHERE c.organization_id = r.organization_id AND c.resource_id = r.id
                             ORDER BY c.capability_id) AS capability_ids
                FROM request_engine.resources r
                WHERE r.organization_id = :organization_id
                  AND (CAST(:after AS uuid) IS NULL OR r.id > :after)
                  AND (CAST(:resource_id AS uuid) IS NULL OR r.id = :resource_id)
                ORDER BY r.id LIMIT :fetch_limit
            """),
                        self._params(query),
                    )
                )
                .mappings()
                .all()
            )
            return tuple(
                ResourceConfiguration(
                    row["id"],
                    row["resource_key"],
                    row["display_name"],
                    row["capacity_model"],
                    row["capacity_units"],
                    row["active"],
                    row["availability_revision"],
                    tuple(cast(list[UUID], row["capability_ids"])),
                )
                for row in rows
            )

    async def read_assignments(
        self, query: SupplyConfigurationQuery
    ) -> tuple[AssignmentConfiguration, ...]:
        async with self._authorized(query, MANAGE_CONTEXTUAL_SUPPLY_SCOPE) as session:
            rows = (
                (
                    await session.execute(
                        text("""
                SELECT a.id, a.resource_id, a.location_id, a.status,
                       lower(a.effective_during) AS effective_from,
                       upper(a.effective_during) AS effective_until,
                       a.revision, r.availability_revision
                FROM request_engine.resource_location_assignments a
                JOIN request_engine.resources r
                  ON r.organization_id = a.organization_id AND r.id = a.resource_id
                WHERE a.organization_id = :organization_id
                  AND (CAST(:after AS uuid) IS NULL OR a.id > :after)
                  AND (CAST(:resource_id AS uuid) IS NULL OR a.resource_id = :resource_id)
                  AND (CAST(:location_id AS uuid) IS NULL OR a.location_id = :location_id)
                  AND (CAST(:assignment_id AS uuid) IS NULL OR a.id = :assignment_id)
                ORDER BY a.id LIMIT :fetch_limit
            """),
                        self._params(query),
                    )
                )
                .mappings()
                .all()
            )
            return tuple(
                AssignmentConfiguration(
                    row["id"],
                    row["resource_id"],
                    row["location_id"],
                    row["status"],
                    row["effective_from"],
                    row["effective_until"],
                    row["revision"],
                    row["availability_revision"],
                )
                for row in rows
            )

    async def read_terms(self, query: SupplyConfigurationQuery) -> tuple[TermsConfiguration, ...]:
        async with self._authorized(query, MANAGE_COMMERCIAL_TERMS_SCOPE) as session:
            rows = (
                (
                    await session.execute(
                        text("""
                SELECT t.id, t.resource_location_assignment_id, t.offering_version_id,
                       lower(t.effective_during) AS effective_from,
                       upper(t.effective_during) AS effective_until,
                       t.amount, t.currency, t.planned_duration_minutes,
                       t.bookable, t.active, t.revision
                FROM request_engine.booking_context_terms t
                WHERE t.organization_id = :organization_id
                  AND (CAST(:after AS uuid) IS NULL OR t.id > :after)
                  AND (CAST(:assignment_id AS uuid) IS NULL
                       OR t.resource_location_assignment_id = :assignment_id)
                ORDER BY t.id LIMIT :fetch_limit
            """),
                        self._params(query),
                    )
                )
                .mappings()
                .all()
            )
            return tuple(
                TermsConfiguration(
                    row["id"],
                    row["resource_location_assignment_id"],
                    row["offering_version_id"],
                    row["effective_from"],
                    row["effective_until"],
                    row["amount"],
                    row["currency"],
                    row["planned_duration_minutes"],
                    row["bookable"],
                    row["active"],
                    row["revision"],
                )
                for row in rows
            )

    @staticmethod
    def _params(query: SupplyConfigurationQuery) -> dict[str, object]:
        return {
            "organization_id": query.organization_id,
            "after": query.after,
            "resource_id": query.resource_id,
            "location_id": query.location_id,
            "assignment_id": query.assignment_id,
            "fetch_limit": query.limit + 1,
        }

    async def read_availability(
        self, query: SupplyConfigurationQuery
    ) -> tuple[AvailabilityConfiguration, ...]:
        async with self._authorized(query, MANAGE_CONTEXTUAL_SUPPLY_SCOPE) as session:
            rows = (
                (
                    await session.execute(
                        text("""
                SELECT w.id, w.resource_location_assignment_id, w.weekday,
                       w.local_start, w.local_end, w.valid_from, w.valid_until,
                       w.active, r.availability_revision
                FROM request_engine.resource_location_availability w
                JOIN request_engine.resource_location_assignments a
                  ON a.organization_id = w.organization_id
                 AND a.id = w.resource_location_assignment_id
                JOIN request_engine.resources r
                  ON r.organization_id = a.organization_id AND r.id = a.resource_id
                WHERE w.organization_id = :organization_id
                  AND w.resource_location_assignment_id = :assignment_id
                  AND (CAST(:after AS uuid) IS NULL OR w.id > :after)
                ORDER BY w.id LIMIT :fetch_limit
            """),
                        self._params(query),
                    )
                )
                .mappings()
                .all()
            )
            return tuple(
                AvailabilityConfiguration(
                    row["id"],
                    row["resource_location_assignment_id"],
                    row["weekday"],
                    row["local_start"],
                    row["local_end"],
                    row["valid_from"],
                    row["valid_until"],
                    row["active"],
                    row["availability_revision"],
                )
                for row in rows
            )

    async def read_exceptions(
        self, query: SupplyConfigurationQuery
    ) -> tuple[ExceptionConfiguration, ...]:
        async with self._authorized(query, MANAGE_CONTEXTUAL_SUPPLY_SCOPE) as session:
            rows = (
                (
                    await session.execute(
                        text("""
                SELECT e.id, a.resource_id, e.resource_location_assignment_id AS assignment_id,
                       lower(e.during) AS start_at, upper(e.during) AS end_at,
                       e.exception_kind, e.reason, e.active, r.availability_revision
                FROM request_engine.resource_location_schedule_exceptions e
                JOIN request_engine.resource_location_assignments a
                  ON a.organization_id = e.organization_id
                 AND a.id = e.resource_location_assignment_id
                JOIN request_engine.resources r
                  ON r.organization_id = a.organization_id AND r.id = a.resource_id
                WHERE e.organization_id = :organization_id
                  AND e.resource_location_assignment_id = :assignment_id
                  AND (CAST(:after AS uuid) IS NULL OR e.id > :after)
                UNION ALL
                SELECT e.id, e.resource_id, NULL::uuid AS assignment_id,
                       lower(e.during) AS start_at, upper(e.during) AS end_at,
                       e.exception_kind, e.reason, true AS active, r.availability_revision
                FROM request_engine.schedule_exceptions e
                JOIN request_engine.resources r
                  ON r.organization_id = e.organization_id AND r.id = e.resource_id
                WHERE e.organization_id = :organization_id
                  AND e.resource_id = :resource_id
                  AND (CAST(:after AS uuid) IS NULL OR e.id > :after)
                ORDER BY id LIMIT :fetch_limit
            """),
                        self._params(query),
                    )
                )
                .mappings()
                .all()
            )
            return tuple(
                ExceptionConfiguration(
                    row["id"],
                    row["resource_id"],
                    row["assignment_id"],
                    row["start_at"],
                    row["end_at"],
                    row["exception_kind"],
                    row["reason"],
                    row["active"],
                    row["availability_revision"],
                )
                for row in rows
            )
