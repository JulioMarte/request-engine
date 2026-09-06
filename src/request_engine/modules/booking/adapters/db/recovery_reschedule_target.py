from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.adapters.db.recovery_contextual_target import (
    validate_contextual_recovery_target,
)
from request_engine.modules.booking.adapters.db.recovery_reschedule_mutation import (
    RecoveryMutationInputs,
)
from request_engine.modules.booking.adapters.db.recovery_reschedule_support import (
    load_active_recovery_claims,
    source_claims_are_contextual,
)
from request_engine.modules.booking.adapters.db.recovery_target_source import (
    validate_recovery_source_checkpoint,
)
from request_engine.modules.booking.adapters.db.reservation_commands import (
    load_requirements,
    lock_resources,
    validate_choice_cardinality,
    validate_resource_capabilities,
)
from request_engine.modules.booking.contracts.recovery import (
    RecoveryBookingConflict,
    RecoveryRescheduleRequest,
)


async def prepare_target_mutation(
    session: AsyncSession,
    *,
    request: RecoveryRescheduleRequest,
    offering_version_id: UUID,
    start_at: datetime,
    end_at: datetime,
    duration_minutes: int,
    base_duration_minutes: int,
    step_minutes: int,
    source_observed_at: datetime,
    source_horizon_end: datetime,
) -> RecoveryMutationInputs:
    requirements = await load_requirements(session, request.organization_id, offering_version_id)
    choices = validate_choice_cardinality(requirements, request.resources)
    old_claims = await load_active_recovery_claims(
        session, request.organization_id, request.reservation_id
    )
    old_resource_ids = tuple(cast(UUID, row["resource_id"]) for row in old_claims)
    if request.source_resource_id not in old_resource_ids:
        raise RecoveryBookingConflict(
            "recovery source Resource is no longer an active Reservation commitment"
        )
    new_resource_ids = tuple(choice.resource_id for choice in choices.values())
    resource_ids = tuple(sorted(set(old_resource_ids + new_resource_ids), key=str))
    resources = await lock_resources(
        session, organization_id=request.organization_id, resource_ids=resource_ids
    )
    await validate_recovery_source_checkpoint(
        session,
        request=request,
        target_start_at=start_at,
        source_observed_at=source_observed_at,
        source_horizon_end=source_horizon_end,
    )
    selected = {resource_id: resources[resource_id] for resource_id in set(new_resource_ids)}
    await validate_resource_capabilities(
        session,
        organization_id=request.organization_id,
        requirements=requirements,
        choices=choices,
        resources=selected,
        location_id=None,
    )
    await validate_contextual_recovery_target(
        session,
        request=request,
        offering_version_id=offering_version_id,
        requirements=requirements,
        choices=choices,
        resources=selected,
        start_at=start_at,
        end_at=end_at,
        base_duration_minutes=base_duration_minutes,
        step_minutes=step_minutes,
        source_contextual=source_claims_are_contextual(old_claims),
    )
    return RecoveryMutationInputs(requirements, choices, old_claims, start_at, end_at)
