from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.adapters.db.reservation_commands import LockedResource
from request_engine.modules.booking.adapters.db.resource_availability import load_live_capacity_claims, load_resource_exceptions, load_resource_schedules
from request_engine.modules.booking.domain.availability import ResourceAvailability


async def load_recovery_profiles_excluding_reservation(session: AsyncSession, *, organization_id: UUID, resources: dict[UUID, LockedResource], start_at: datetime, end_at: datetime, reservation_id: UUID) -> dict[UUID, ResourceAvailability]:
    resource_ids = tuple(sorted(resources, key=str))
    schedules = await load_resource_schedules(session, organization_id, resource_ids)
    exceptions = await load_resource_exceptions(session, organization_id, resource_ids, start_at, end_at)
    claims = await load_live_capacity_claims(session, organization_id, resource_ids, start_at, end_at, exclude_reservation_id=reservation_id)
    return {
        resource_id: ResourceAvailability(capacity_model=resource.capacity_model, capacity_units=resource.capacity_units, default_timezone=resource.default_timezone, schedules=schedules.get(resource_id, ()), exceptions=exceptions.get(resource_id, ()), live_claims=claims.get(resource_id, ()))
        for resource_id, resource in resources.items()
    }
