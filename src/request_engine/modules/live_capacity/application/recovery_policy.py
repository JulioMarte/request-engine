from request_engine.modules.booking.contracts.live_capacity import (
    OperationalAvailabilityInterval,
    PlannedWorkloadFact,
)
from request_engine.modules.live_capacity.contracts.recovery import RecoveryCommitmentFact


def affected_recovery_commitments(
    planned: tuple[PlannedWorkloadFact, ...],
    intervals: tuple[OperationalAvailabilityInterval, ...],
    scheduled_shortfall_seconds: int,
) -> tuple[RecoveryCommitmentFact, ...]:
    """Return only Reservation commitments proven unsatisfied by schedule authority.

    QueueEntry/ServiceSession pressure is intentionally absent from this function.
    Live workload can make recovery operationally at-risk, but it does not prove
    which future Reservation should be displaced. Fabricating that causal link
    would allow F5 to reschedule an otherwise valid commitment.
    """

    if scheduled_shortfall_seconds <= 0:
        return ()

    ordered = sorted(
        planned,
        key=lambda item: (item.planned_starts_at, str(item.reservation_id)),
    )
    selected = [
        item
        for item in ordered
        if not any(
            interval.starts_at <= item.planned_starts_at
            and item.planned_ends_at <= interval.ends_at
            for interval in intervals
        )
    ]

    result: list[RecoveryCommitmentFact] = []
    for item in selected:
        if item.subject_party_id is None:
            raise RuntimeError(
                "authoritative planned Reservation is missing subject Party provenance"
            )
        result.append(
            RecoveryCommitmentFact(
                reservation_id=item.reservation_id,
                offering_version_id=item.offering_version_id,
                subject_party_id=item.subject_party_id,
                reservation_revision=item.reservation_revision,
                planned_starts_at=item.planned_starts_at,
                planned_ends_at=item.planned_ends_at,
                planned_duration_seconds=item.planned_duration_seconds or 0,
            )
        )
    return tuple(result)
