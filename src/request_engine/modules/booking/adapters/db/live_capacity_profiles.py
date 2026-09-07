from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.adapters.db.contextual_supply import (
    load_assignment_exceptions,
    load_assignment_schedules,
    load_contextualization,
    load_location_observations,
)
from request_engine.modules.booking.adapters.db.live_capacity_commitments import (
    load_unplanned_live_claims,
)
from request_engine.modules.booking.adapters.db.live_capacity_resource import (
    load_projection_resource,
)
from request_engine.modules.booking.adapters.db.resource_availability import (
    load_resource_exceptions,
)
from request_engine.modules.booking.domain.availability import ResourceAvailability


@dataclass(frozen=True, slots=True)
class AvailabilityWindow:
    profiles: tuple[ResourceAvailability, ...]
    effective_start: datetime | None
    effective_end: datetime | None


async def load_availability_windows(
    session: AsyncSession,
    *,
    organization_id: UUID,
    resource_id: UUID,
    location_id: UUID,
    observed_at: datetime,
    horizon_end: datetime,
) -> tuple[AvailabilityWindow, ...] | None:
    resource = await load_projection_resource(
        session, organization_id=organization_id, resource_id=resource_id
    )
    if resource is None or not resource.supports_sequential_projection:
        return None
    broad = await load_resource_exceptions(
        session, organization_id, (resource_id,), observed_at, horizon_end
    )
    opaque_claims = await load_unplanned_live_claims(
        session,
        organization_id=organization_id,
        resource_id=resource_id,
        observed_at=observed_at,
        horizon_end=horizon_end,
    )
    _, by_resource = await load_contextualization(
        session, organization_id, (resource_id,), observed_at, horizon_end
    )
    assignments = tuple(
        item for item in by_resource.get(resource_id, ()) if item.location_id == location_id
    )
    if not assignments:
        return None
    assignment_ids = tuple(item.id for item in assignments)
    schedules = await load_assignment_schedules(session, organization_id, assignment_ids)
    exceptions = await load_assignment_exceptions(
        session, organization_id, assignment_ids, observed_at, horizon_end
    )
    locations = await load_location_observations(
        session, organization_id, (location_id,), observed_at, horizon_end
    )
    location = locations.get(location_id)
    if location is None:
        return None
    return tuple(
        AvailabilityWindow(
            profiles=(
                ResourceAvailability(
                    capacity_model=resource.capacity_model,
                    capacity_units=resource.capacity_units,
                    default_timezone=location.timezone,
                    schedules=schedules.get(assignment.id, ()),
                    exceptions=broad.get(resource_id, ()) + exceptions.get(assignment.id, ()),
                    live_claims=opaque_claims,
                ),
                location.profile,
            ),
            effective_start=assignment.effective_start,
            effective_end=assignment.effective_end,
        )
        for assignment in assignments
    )
