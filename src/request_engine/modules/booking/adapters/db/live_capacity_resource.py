from dataclasses import dataclass
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.domain.availability import CapacityModel


@dataclass(frozen=True, slots=True)
class ProjectionResource:
    capacity_model: CapacityModel
    capacity_units: int

    @property
    def supports_sequential_projection(self) -> bool:
        return self.capacity_model is CapacityModel.EXCLUSIVE and self.capacity_units == 1


async def load_projection_resource(
    session: AsyncSession,
    *,
    organization_id: UUID,
    resource_id: UUID,
) -> ProjectionResource | None:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT capacity_model, capacity_units
                    FROM request_engine.resources
                    WHERE organization_id = :organization_id
                      AND id = :resource_id
                      AND active
                    """
                ),
                {"organization_id": organization_id, "resource_id": resource_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    return ProjectionResource(
        capacity_model=CapacityModel(cast(str, row["capacity_model"])),
        capacity_units=cast(int, row["capacity_units"]),
    )
