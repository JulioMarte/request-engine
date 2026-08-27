from collections.abc import Mapping
from dataclasses import dataclass
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
    await _replace_claims(session, request=request, inputs=inputs)


async def _replace_claims(
    session: AsyncSession,
    *,
    request: RecoveryRescheduleRequest,
    inputs: RecoveryMutationInputs,
) -> None:
    old_by_requirement = {
        cast(UUID, row["requirement_id"]): cast(UUID, row["id"])
        for row in inputs.old_claims
    }
    if set(old_by_requirement) != set(inputs.requirements):
        raise RuntimeError("Reservation no longer has the canonical claim set")
    replacement_ids: dict[UUID, UUID] = {}
    for requirement in sorted(inputs.requirements.values(), key=lambda item: item.ordinal):
        replacement_ids[requirement.id] = await _insert_claim(
            session,
            request=request,
            inputs=inputs,
            requirement=requirement,
        )
    replace_sql = """
        UPDATE request_engine.capacity_claims
        SET status = 'replaced', replaced_by_claim_id = :new_claim_id,
            updated_at = clock_timestamp()
        WHERE organization_id = :organization_id AND id = :old_claim_id
          AND status = 'released'
    """
    for requirement_id, old_claim_id in old_by_requirement.items():
        await session.execute(
            text(replace_sql),
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
    inputs: RecoveryMutationInputs,
    requirement: RequirementLike,
) -> UUID:
    sql = """
        INSERT INTO request_engine.capacity_claims (
            organization_id, resource_id, requirement_id, reservation_id, during, quantity
        ) VALUES (
            :organization_id, :resource_id, :requirement_id, :reservation_id,
            tstzrange(:start_at, :end_at, '[)'), :quantity
        ) RETURNING id
    """
    choice = inputs.choices[requirement.id]
    row = await session.execute(
        text(sql),
        {
            "organization_id": request.organization_id,
            "resource_id": choice.resource_id,
            "requirement_id": requirement.id,
            "reservation_id": request.reservation_id,
            "start_at": inputs.start_at,
            "end_at": inputs.end_at,
            "quantity": requirement.quantity,
        },
    )
    return cast(UUID, row.scalar_one())
