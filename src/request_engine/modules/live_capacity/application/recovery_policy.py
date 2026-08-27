from request_engine.modules.booking.contracts.live_capacity import (
    OperationalAvailabilityInterval,
    PlannedWorkloadFact,
)
from request_engine.modules.live_capacity.contracts.recovery import RecoveryCommitmentFact


def affected_recovery_commitments(
    planned: tuple[PlannedWorkloadFact, ...],
    intervals: tuple[OperationalAvailabilityInterval, ...],
    shortfall_seconds: int,
    *,
    live_pressure_seconds: int = 0,
) -> tuple[RecoveryCommitmentFact, ...]:
    """Return commitments that are structurally or live-pressure displaced.

    Capacity loss selects only Reservations that no longer fit their authoritative
    remaining interval. Additional pressure created by live Queue/ServiceSession
    workload is resolved deterministically from the latest still-planned
    Reservations backwards, because those are the commitments displaced first
    once already-running/waiting work consumes the remaining day.
    """

    if shortfall_seconds <= 0:
        return ()

    ordered = sorted(
        planned,
        key=lambda item: (item.planned_starts_at, str(item.reservation_id)),
    )
    directly_unsatisfied = [
        item
        for item in ordered
        if not any(
            interval.starts_at <= item.planned_starts_at
            and item.planned_ends_at <= interval.ends_at
            for interval in intervals
        )
    ]
    selected_ids = {item.reservation_id for item in directly_unsatisfied}
    selected = list(directly_unsatisfied)

    remaining_live_pressure = max(live_pressure_seconds, 0)
    if remaining_live_pressure:
        for item in reversed(ordered):
            if item.reservation_id in selected_ids:
                continue
            selected.append(item)
            selected_ids.add(item.reservation_id)
            remaining_live_pressure -= item.planned_duration_seconds or 0
            if remaining_live_pressure <= 0:
                break

    selected.sort(key=lambda item: (item.planned_starts_at, str(item.reservation_id)))
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
                contextual_commitment=item.contextual_commitment,
            )
        )
    return tuple(result)
