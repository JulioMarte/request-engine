from typing import cast
from uuid import UUID

from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.discovery.adapters.db import mapping_store
from request_engine.modules.discovery.application.commands.mapping import (
    MapOfferingToServiceClassificationCommand,
)
from request_engine.modules.discovery.application.errors import (
    DiscoveryConfigurationConflict,
    DiscoveryRevisionConflict,
)


async def persist_mapping(
    session: AsyncSession,
    command: MapOfferingToServiceClassificationCommand,
    current: RowMapping | None,
    classification_id: UUID,
) -> RowMapping:
    if current is None:
        if command.expected_revision is not None:
            raise DiscoveryConfigurationConflict("mapping does not yet exist")
        return await mapping_store.insert_mapping(
            session, command.organization_id, command.offering_id, classification_id
        )
    actual = cast(int, current["revision"])
    if command.expected_revision != actual:
        raise DiscoveryRevisionConflict(
            cast(UUID, current["id"]), command.expected_revision or 0, actual
        )
    if cast(UUID, current["service_classification_id"]) == classification_id:
        return current
    return await mapping_store.replace_mapping(
        session,
        command.organization_id,
        command.offering_id,
        cast(UUID, current["id"]),
        classification_id,
    )
