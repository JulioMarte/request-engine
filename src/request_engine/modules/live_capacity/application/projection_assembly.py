from request_engine.modules.live_capacity.application.projection_snapshot import ProjectionSnapshot
from request_engine.modules.live_capacity.application.workload_builder import (
    build_remaining_work,
    scheduled_work,
)
from request_engine.modules.live_capacity.contracts.projection import (
    CapacityInterval,
    LiveCapacityProjection,
    ProjectionWorkItem,
)
from request_engine.modules.live_capacity.domain.projection import project_live_capacity


def existing_work(snapshot: ProjectionSnapshot) -> tuple[ProjectionWorkItem, ...]:
    return build_remaining_work(
        queue=snapshot.queue,
        delivery=snapshot.delivery,
        planned=snapshot.booking.planned_same_day_work,
        estimates=snapshot.estimates,
    )


def scheduled_commitments(snapshot: ProjectionSnapshot) -> tuple[ProjectionWorkItem, ...]:
    return scheduled_work(snapshot.booking.planned_same_day_work)


def capacity_intervals(snapshot: ProjectionSnapshot) -> tuple[CapacityInterval, ...]:
    return tuple(
        CapacityInterval(item.starts_at, item.ends_at)
        for item in snapshot.booking.remaining_intervals
    )


def has_open_interruption(snapshot: ProjectionSnapshot) -> bool:
    return (
        snapshot.delivery.active_service is not None
        and snapshot.delivery.active_service.has_open_interruption
    )


def assemble_live_capacity_projection(snapshot: ProjectionSnapshot) -> LiveCapacityProjection:
    """Project one authoritative snapshot with the canonical F4 semantics."""

    return project_live_capacity(
        observed_at=snapshot.observed_at,
        intervals=capacity_intervals(snapshot),
        work_items=existing_work(snapshot),
        scheduled_work_items=scheduled_commitments(snapshot),
        has_open_interruption=has_open_interruption(snapshot),
        has_open_resource_activity=snapshot.delivery.open_resource_activity is not None,
    )
