from uuid import UUID

from request_engine.modules.booking.contracts.live_capacity import PlannedWorkloadFact
from request_engine.modules.delivery.contracts.live_capacity import DeliveryProjectionSnapshot
from request_engine.modules.live_capacity.contracts.projection import (
    EstimateSource,
    ProjectionWorkItem,
    WorkloadEstimate,
)
from request_engine.modules.live_capacity.domain.deduplication import deduplicate_remaining_work
from request_engine.modules.queue.contracts.live_capacity import (
    QueueProjectionEntry,
    QueueProjectionSnapshot,
)

_UNKNOWN = WorkloadEstimate(None, EstimateSource.UNKNOWN)


def build_remaining_work(
    *,
    queue: QueueProjectionSnapshot,
    delivery: DeliveryProjectionSnapshot,
    planned: tuple[PlannedWorkloadFact, ...],
    estimates: dict[UUID, WorkloadEstimate],
) -> tuple[ProjectionWorkItem, ...]:
    planned_by_reservation = {item.reservation_id: item for item in planned}
    queued = tuple(
        _queue_item(
            entry,
            _estimate_with_planned_fallback(
                entry.expected_workload_classification_id,
                entry.reservation_id,
                estimates,
                planned_by_reservation,
            ),
        )
        for entry in queue.entries
    )
    active: tuple[ProjectionWorkItem, ...] = ()
    if delivery.active_service is not None:
        service = delivery.active_service
        queue_entry = next(
            (item for item in queue.entries if item.queue_entry_id == service.queue_entry_id), None
        )
        workload_id = service.actual_workload_classification_id
        if workload_id is None and queue_entry is not None:
            workload_id = queue_entry.expected_workload_classification_id
        reservation_id = queue_entry.reservation_id if queue_entry is not None else None
        estimate = _estimate_with_planned_fallback(
            workload_id,
            reservation_id,
            estimates,
            planned_by_reservation,
        )
        active = (
            ProjectionWorkItem(
                key=service.service_session_id,
                duration_seconds=estimate.duration_seconds,
                source=estimate.source,
                queue_entry_id=service.queue_entry_id,
                reservation_id=reservation_id,
                active_service_seconds=service.active_service_seconds,
            ),
        )
    planned_items = scheduled_work(planned)
    return deduplicate_remaining_work(planned=planned_items, queued=queued, active=active)


def scheduled_work(planned: tuple[PlannedWorkloadFact, ...]) -> tuple[ProjectionWorkItem, ...]:
    return tuple(
        ProjectionWorkItem(
            key=item.reservation_id,
            duration_seconds=item.planned_duration_seconds,
            source=(
                EstimateSource.PLANNED_DURATION
                if item.planned_duration_seconds is not None
                else EstimateSource.UNKNOWN
            ),
            reservation_id=item.reservation_id,
        )
        for item in planned
    )


def _estimate_for(
    workload_id: UUID | None,
    estimates: dict[UUID, WorkloadEstimate],
) -> WorkloadEstimate:
    if workload_id is None:
        return _UNKNOWN
    return estimates.get(workload_id, _UNKNOWN)


def _estimate_with_planned_fallback(
    workload_id: UUID | None,
    reservation_id: UUID | None,
    estimates: dict[UUID, WorkloadEstimate],
    planned_by_reservation: dict[UUID, PlannedWorkloadFact],
) -> WorkloadEstimate:
    estimate = _estimate_for(workload_id, estimates)
    if estimate.duration_seconds is not None:
        return estimate
    if reservation_id is None:
        return estimate
    planned = planned_by_reservation.get(reservation_id)
    if planned is None or planned.planned_duration_seconds is None:
        return estimate
    return WorkloadEstimate(planned.planned_duration_seconds, EstimateSource.PLANNED_DURATION)


def _queue_item(
    entry: QueueProjectionEntry,
    estimate: WorkloadEstimate,
) -> ProjectionWorkItem:
    return ProjectionWorkItem(
        key=entry.queue_entry_id,
        duration_seconds=estimate.duration_seconds,
        source=estimate.source,
        queue_entry_id=entry.queue_entry_id,
        reservation_id=entry.reservation_id,
    )
