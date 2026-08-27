from request_engine.modules.live_capacity.application.projection_snapshot import ProjectionSnapshot
from request_engine.modules.live_capacity.contracts.projection import LiveCapacityProjection
from request_engine.modules.live_capacity.contracts.recovery import (
    RecoveryCapacityCheckpoint,
    RecoveryCommitmentCheckpoint,
)


def build_recovery_checkpoint(
    snapshot: ProjectionSnapshot,
    *,
    resource_availability_revision: int,
    location_operational_revision: int,
    recovery_source_revision: int,
) -> RecoveryCapacityCheckpoint:
    return RecoveryCapacityCheckpoint(
        projection_policy_revision=snapshot.policy.revision,
        resource_availability_revision=resource_availability_revision,
        location_operational_revision=location_operational_revision,
        recovery_source_revision=recovery_source_revision,
        commitments=tuple(
            RecoveryCommitmentCheckpoint(
                reservation_id=item.reservation_id,
                revision=item.reservation_revision,
                starts_at=item.planned_starts_at,
                ends_at=item.planned_ends_at,
            )
            for item in sorted(
                snapshot.booking.planned_same_day_work,
                key=lambda value: (value.planned_starts_at, str(value.reservation_id)),
            )
        ),
    )


def recovery_pressure(projection: LiveCapacityProjection) -> tuple[int, int, int]:
    """Return committed, scheduled shortfall and live shortfall independently.

    Scheduled shortfall answers whether persisted Reservation commitments exceed
    executable capacity. Live shortfall includes QueueEntry/ServiceSession work
    from the same authoritative F4 projection. The latter is diagnostic pressure;
    it must never by itself identify a Reservation as affected.
    """

    executable = projection.remaining_operational_seconds
    committed = projection.scheduled_committed_workload_seconds or 0
    scheduled_shortfall = max(committed - executable, 0)
    projected_workload = projection.projected_remaining_workload_seconds
    live_shortfall = (
        scheduled_shortfall
        if projected_workload is None
        else max(projected_workload - executable, 0)
    )
    return committed, scheduled_shortfall, live_shortfall
