from typing import cast
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.catalog.adapters.db.offering_policy_commands import (
    policy_input_from_json,
)
from request_engine.modules.catalog.application.commands.bootstrap_catalog import (
    OfferingRequirementInput,
    ResourceCapabilityState,
)
from request_engine.modules.catalog.application.queries.read_configuration import (
    OfferingConfiguration,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.db.tenant_principal_authority_reader import (
    require_current_tenant_capability,
)


class PostgresCatalogConfigurationReader:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def list_resource_capabilities(
        self,
        organization_id: UUID,
        *,
        principal_id: UUID,
        limit: int,
        after_id: UUID | None,
    ) -> tuple[ResourceCapabilityState, ...]:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            await require_current_tenant_capability(
                session,
                organization_id=organization_id,
                principal_id=principal_id,
                capability="catalog.read_configuration",
            )
            rows = (
                (
                    await session.execute(
                        text("""
                SELECT id, capability_key, display_name FROM request_engine.resource_capabilities
                WHERE organization_id=:organization_id
                  AND (CAST(:after_id AS uuid) IS NULL OR id > CAST(:after_id AS uuid))
                ORDER BY id LIMIT :limit
            """),
                        {"organization_id": organization_id, "after_id": after_id, "limit": limit},
                    )
                )
                .mappings()
                .all()
            )
        return tuple(
            ResourceCapabilityState(
                cast(UUID, row["id"]),
                cast(str, row["capability_key"]),
                cast(str, row["display_name"]),
            )
            for row in rows
        )

    async def read_offering_configuration(
        self,
        organization_id: UUID,
        offering_version_id: UUID,
        *,
        principal_id: UUID,
    ) -> OfferingConfiguration | None:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            await require_current_tenant_capability(
                session,
                organization_id=organization_id,
                principal_id=principal_id,
                capability="catalog.read_configuration",
            )
            params = {"organization_id": organization_id, "version_id": offering_version_id}
            row = (
                (
                    await session.execute(
                        text("""
                SELECT o.id AS offering_id, o.offering_key, o.active, v.id, v.version,
                       COALESCE(p.revision, 0) AS policy_revision,
                       COALESCE(p.booking_policy, v.booking_policy) AS booking_policy
                FROM request_engine.offering_versions v
                JOIN request_engine.offerings o
                  ON o.organization_id=v.organization_id AND o.id=v.offering_id
                LEFT JOIN LATERAL (
                    SELECT revision, booking_policy
                    FROM request_engine.offering_version_booking_policies
                    WHERE organization_id=v.organization_id AND offering_version_id=v.id
                    ORDER BY revision DESC LIMIT 1
                ) p ON true
                WHERE v.organization_id=:organization_id AND v.id=:version_id
            """),
                        params,
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            requirements = (
                (
                    await session.execute(
                        text("""
                SELECT capability_id, quantity FROM request_engine.offering_resource_requirements
                WHERE organization_id=:organization_id AND offering_version_id=:version_id
                ORDER BY ordinal, id
            """),
                        params,
                    )
                )
                .mappings()
                .all()
            )
            return OfferingConfiguration(
                offering_id=cast(UUID, row["offering_id"]),
                offering_version_id=cast(UUID, row["id"]),
                offering_key=cast(str, row["offering_key"]),
                version=cast(int, row["version"]),
                active=cast(bool, row["active"]),
                requirements=tuple(
                    OfferingRequirementInput(
                        cast(UUID, item["capability_id"]),
                        cast(int, item["quantity"]),
                    )
                    for item in requirements
                ),
                booking_policy_revision=cast(int, row["policy_revision"]),
                booking_policy=policy_input_from_json(
                    cast(dict[str, object], row["booking_policy"])
                ),
            )
