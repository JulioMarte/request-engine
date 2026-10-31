from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ServingResource:
    """A Resource that ``service_session.start`` would accept at a Location right now."""

    resource_id: UUID
    display_name: str


@dataclass(frozen=True, slots=True)
class LocationServingResources:
    location_id: UUID
    observed_at: datetime
    resources: tuple[ServingResource, ...]
