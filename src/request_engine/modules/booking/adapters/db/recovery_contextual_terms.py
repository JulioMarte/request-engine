from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.adapters.db.contextual_recovery_shared import (
    effective_context_observations,
)
from request_engine.modules.booking.adapters.db.recovery_commercial_guard import (
    require_preserved_commercial_commitment,
)
from request_engine.modules.booking.adapters.db.recovery_contextual_snapshot import (
    ContextualRecoverySnapshot,
)
from request_engine.modules.booking.contracts.recovery import (
    RecoveryRescheduleRequest,
    RecoveryTargetUnavailable,
)
from request_engine.modules.booking.domain.contextual_supply import (
    ConflictingContextualTerms,
    ContextBookingTerms,
    ContextNotBookable,
    MissingCommercialTerms,
    ResolvedBookingTerms,
    resolve_booking_terms,
)


async def resolve_recovery_terms(
    session: AsyncSession,
    *,
    request: RecoveryRescheduleRequest,
    snapshot: ContextualRecoverySnapshot,
    start_at: datetime,
    source_contextual: bool,
) -> tuple[ResolvedBookingTerms, tuple[ContextBookingTerms | None, ...]]:
    observations = effective_context_observations(
        snapshot.ordered_requirement_ids,
        snapshot.selected_assignments,
        snapshot.context_terms,
        start_at,
    )
    try:
        resolved = resolve_booking_terms(snapshot.base_terms, observations)
    except (MissingCommercialTerms, ConflictingContextualTerms, ContextNotBookable) as exc:
        raise RecoveryTargetUnavailable("contextual commercial terms changed") from exc
    if (
        resolved.amount != request.expected_amount
        or resolved.currency != request.expected_currency
        or resolved.planned_duration_minutes != request.expected_planned_duration_minutes
    ):
        raise RecoveryTargetUnavailable("contextual option terms changed")
    if source_contextual:
        await require_preserved_commercial_commitment(
            session,
            organization_id=request.organization_id,
            reservation_id=request.reservation_id,
            resolved=resolved,
        )
    return resolved, observations
