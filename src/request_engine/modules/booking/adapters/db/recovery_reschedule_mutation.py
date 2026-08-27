from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.adapters.db.recovery_claim_mutation import (
    RequirementLike,
    replace_capacity_claims,
)
from request_engine.modules.booking.contracts.appointments import ResourceChoice
from request_engine.modules.booking.contracts.recovery import RecoveryRescheduleRequest


@dataclass(frozen=True, slots=True)
class RecoveryMutationInputs:
    requirements: Mapping[UUID, RequirementLike]
    choices: dict[UUID, ResourceChoice]
    old_claims: tuple[RowMapping, ...]
    start_at: datetime
    end_at: datetime


async def replace_reservation_commitment(
    session: AsyncSession,
    *,
    request: RecoveryRescheduleRequest,
    inputs: RecoveryMutationInputs,
) -> None:
    release_sql = """
        UPDATE request_engine.capacity_claims
        SET status = 'released', released_at = clock_timestamp(),
            updated_at = clock_timestamp()
        WHERE organization_id = :organization_id
          AND reservation_id = :reservation_id AND status = 'active'
    """
    await session.execute(
        text(release_sql),
        {
            "organization_id": request.organization_id,
            "reservation_id": request.reservation_id,
        },
    )
    update_sql = """
        UPDATE request_engine.reservations
        SET location_id = :location_id, during = tstzrange(:start_at, :end_at, '[)'),
            revision = revision + 1, updated_at = clock_timestamp()
        WHERE organization_id = :organization_id AND id = :reservation_id
    """
    await session.execute(
        text(update_sql),
        {
            "organization_id": request.organization_id,
            "reservation_id": request.reservation_id,
            "location_id": request.location_id,
            "start_at": inputs.start_at,
            "end_at": inputs.end_at,
        },
    )
    await replace_capacity_claims(
        session,
        request=request,
        requirements=inputs.requirements,
        choices=inputs.choices,
        old_claims=inputs.old_claims,
        start_at=inputs.start_at,
        end_at=inputs.end_at,
    )
