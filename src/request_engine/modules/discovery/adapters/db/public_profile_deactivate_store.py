from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.discovery.application.errors import (
    DiscoveryConfigurationConflict,
    DiscoveryRevisionConflict,
)


async def deactivate_profile(
    session: AsyncSession,
    *,
    organization_id: UUID,
    resource_id: UUID,
    expected_revision: int,
) -> RowMapping:
    current = (
        (
            await session.execute(
                text(
                    "SELECT active, revision FROM request_engine.resource_public_profiles "
                    "WHERE organization_id=:org AND resource_id=:resource FOR UPDATE"
                ),
                {"org": organization_id, "resource": resource_id},
            )
        )
        .mappings()
        .first()
    )
    if current is None:
        raise DiscoveryConfigurationConflict("public profile does not exist")
    actual = cast(int, current["revision"])
    if expected_revision != actual:
        raise DiscoveryRevisionConflict(resource_id, expected_revision, actual)
    if not cast(bool, current["active"]):
        raise DiscoveryConfigurationConflict("public profile is already inactive")
    return (
        (
            await session.execute(
                text(
                    "UPDATE request_engine.resource_public_profiles SET active=false,"
                    "revision=revision+1 WHERE organization_id=:org AND resource_id=:resource "
                    "AND revision=:expected RETURNING display_name,role_label,"
                    "profile_image_ref,active,revision"
                ),
                {"org": organization_id, "resource": resource_id, "expected": expected_revision},
            )
        )
        .mappings()
        .one()
    )
