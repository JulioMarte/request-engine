from collections.abc import Mapping
from datetime import datetime
from typing import Protocol, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.contracts.appointments import ResourceChoice
from request_engine.modules.booking.contracts.recovery import RecoveryRescheduleRequest


class RequirementLike(Protocol):
    @property
    def id(self) -> UUID: ...

    @property
    def ordinal(self) -> int: ...

    @property
    def quantity(self) -> int: ...


async def replace_capacity_claims(
    session: AsyncSession,
    *,
    request: RecoveryRescheduleRequest,
    requirements: Mapping[UUID, RequirementLike],
    choices: dict[UUID, ResourceChoice],
    old_claims: tuple[RowMapping, ...],
    start_at: datetime,
    end_at: datetime,
) -> None:
    old_by_requirement = {
        cast(UUID, row["requirement_id"]): cast(UUID, row["id"])
        for row in old_claims
    }
    if set(old_by_requirement) != set(requirements):
        raise RuntimeError("Reservation no longer has the canonical claim set")
    replacement_ids: dict[UUID, UUID] = {}
    for requirement in sorted(requirements.values(), key=lambda item: item.ordinal):
        replacement_ids[requirement.id] = await _insert_claim(
            session,
            request=request,
            requirement=requirement,
            choice=choices[requirement.id],
            start_at=start_at,
            end_at=end_at,
        )
    sql = """
        UPDATE request_engine.capacity_claims
        SET status = 'replaced', replaced_by_claim_id = :new_claim_id,
            updated_at = clock_timestamp()
        WHERE organization_id = :organization_id AND id = :old_claim_id
          AND status = 'released'
    """
    for requirement_id, old_claim_id in old_by_requirement.items():
        await session.execute(
            text(sql),
            {
                "organization_id": request.organization_id,
                "old_claim_id": old_claim_id,
                "new_claim_id": replacement_ids[requirement_id],
            },
        )


async def _insert_claim(
    session: AsyncSession,
    *,
    request: RecoveryRescheduleRequest,
    requirement: RequirementLike,
    choice: ResourceChoice,
    start_at: datetime,
    end_at: datetime,
) -> UUID:
    sql = """
        INSERT INTO request_engine.capacity_claims (
            organization_id, resource_id, requirement_id, reservation_id, during, quantity
        ) VALUES (
            :organization_id, :resource_id, :requirement_id, :reservation_id,
            tstzrange(:start_at, :end_at, '[)'), :quantity
        ) RETURNING id
    """
    row = await session.execute(
        text(sql),
        {
            "organization_id": request.organization_id,
            "resource_id": choice.resource_id,
            "requirement_id": requirement.id,
            "reservation_id": request.reservation_id,
            "start_at": start_at,
            "end_at": end_at,
            "quantity": requirement.quantity,
        },
    )
    return cast(UUID, row.scalar_one())
