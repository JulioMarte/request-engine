from request_engine.modules.live_capacity.application.projection_snapshot import ProjectionSnapshot
from request_engine.modules.live_capacity.application.workload_builder import build_remaining_work
from request_engine.modules.live_capacity.contracts.projection import (
    CapacityInterval,
    ProjectionWorkItem,
)


def existing_work(snapshot: ProjectionSnapshot) -> tuple[ProjectionWorkItem, ...]:
    return build_remaining_work(
        queue=snapshot.queue,
        delivery=snapshot.delivery,
        planned=snapshot.booking.planned_same_day_work,
        estimates=snapshot.estimates,
    )


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
