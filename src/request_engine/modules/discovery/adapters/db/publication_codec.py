from datetime import datetime
from typing import cast
from uuid import UUID

from request_engine.modules.discovery.application.commands.publication import (
    DiscoveryPublicationState,
)


def state_to_json(state: DiscoveryPublicationState) -> dict[str, object]:
    return {
        "id": str(state.id),
        "offering_id": str(state.offering_id),
        "location_id": str(state.location_id),
        "resource_id": str(state.resource_id) if state.resource_id else None,
        "effective_start": state.effective_start.isoformat(),
        "effective_end": state.effective_end.isoformat() if state.effective_end else None,
        "provider_visibility": state.provider_visibility,
        "status": state.status,
        "revision": state.revision,
    }


def state_from_json(value: dict[str, object]) -> DiscoveryPublicationState:
    resource_id = cast(str | None, value.get("resource_id"))
    effective_end = cast(str | None, value.get("effective_end"))
    return DiscoveryPublicationState(
        id=UUID(cast(str, value["id"])),
        offering_id=UUID(cast(str, value["offering_id"])),
        location_id=UUID(cast(str, value["location_id"])),
        resource_id=UUID(resource_id) if resource_id else None,
        effective_start=datetime.fromisoformat(cast(str, value["effective_start"])),
        effective_end=datetime.fromisoformat(effective_end) if effective_end else None,
        provider_visibility=cast(str, value["provider_visibility"]),
        status=cast(str, value["status"]),
        revision=cast(int, value["revision"]),
    )
