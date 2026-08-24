from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy.engine import RowMapping

from request_engine.modules.discovery.application.commands.publication import (
    DiscoveryPublicationState,
    PublishDiscoverySupplyCommand,
)


def created_state(
    row: RowMapping,
    command: PublishDiscoverySupplyCommand,
    *,
    effective_start: datetime,
    effective_end: datetime | None,
    provider_visibility: str,
) -> DiscoveryPublicationState:
    return DiscoveryPublicationState(
        id=cast(UUID, row["id"]),
        offering_id=command.offering_id,
        location_id=command.location_id,
        resource_id=command.resource_id,
        effective_start=effective_start,
        effective_end=effective_end,
        provider_visibility=provider_visibility,
        status="active",
        revision=cast(int, row["revision"]),
    )
