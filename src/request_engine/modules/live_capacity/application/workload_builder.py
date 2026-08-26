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
    queued = tuple(
        _queue_item(
            entry,
            _estimate_for(entry.expected_workload_classification_id, estimates),
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
        estimate = _estimate_for(workload_id, estimates)
        active = (
            ProjectionWorkItem(
                key=service.service_session_id,
                duration_seconds=estimate.duration_seconds,
                source=estimate.source,
                queue_entry_id=service.queue_entry_id,
                reservation_id=queue_entry.reservation_id if queue_entry is not None else None,
                active_service_seconds=service.active_service_seconds,
            ),
        )
    planned_items = tuple(
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
    return deduplicate_remaining_work(planned=planned_items, queued=queued, active=active)


def _estimate_for(
    workload_id: UUID | None,
    estimates: dict[UUID, WorkloadEstimate],
) -> WorkloadEstimate:
    if workload_id is None:
        return _UNKNOWN
    return estimates.get(workload_id, _UNKNOWN)


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
