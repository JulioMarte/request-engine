from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.live_capacity.application.errors import (
    InvalidWorkloadEstimateConfiguration,
)


async def validate_workload_estimate_target(
    session: AsyncSession,
    *,
    organization_id: UUID,
    workload_classification_id: UUID,
) -> None:
    active = await session.scalar(
        text(
            "SELECT active FROM request_engine.operational_workload_classifications "
            "WHERE organization_id=:organization_id AND id=:workload_classification_id "
            "FOR SHARE"
        ),
        {
            "organization_id": organization_id,
            "workload_classification_id": workload_classification_id,
        },
    )
    if active is not True:
        raise InvalidWorkloadEstimateConfiguration(workload_classification_id)
