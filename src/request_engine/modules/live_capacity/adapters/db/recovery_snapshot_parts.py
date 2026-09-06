from request_engine.modules.booking.contracts.live_capacity import PlannedWorkloadFact
from request_engine.modules.delivery.contracts.live_capacity import DeliveryProjectionSnapshot
from request_engine.modules.live_capacity.contracts.projection import ProjectionWorkItem
from request_engine.modules.queue.contracts.live_capacity import QueueProjectionSnapshot


def planned_payload(planned: tuple[PlannedWorkloadFact, ...]) -> list[dict[str, object]]:
    return [
        {
            "reservation_id": str(item.reservation_id),
            "revision": item.reservation_revision,
            "offering_version_id": str(item.offering_version_id),
            "subject_party_id": str(item.subject_party_id) if item.subject_party_id else None,
            "starts_at": item.planned_starts_at.isoformat(),
            "ends_at": item.planned_ends_at.isoformat(),
            "duration_seconds": item.planned_duration_seconds,
        }
        for item in sorted(
            planned,
            key=lambda value: (value.planned_starts_at, str(value.reservation_id)),
        )
    ]


def queue_payload(queue: QueueProjectionSnapshot) -> list[dict[str, object]]:
    return [
        {
            "queue_entry_id": str(item.queue_entry_id),
            "reservation_id": str(item.reservation_id) if item.reservation_id else None,
            "status": item.status,
            "arrived_at": item.arrived_at.isoformat(),
            "admitted_at": item.admitted_at.isoformat(),
            "called_at": item.called_at.isoformat() if item.called_at else None,
            "expected_workload_classification_id": (
                str(item.expected_workload_classification_id)
                if item.expected_workload_classification_id
                else None
            ),
        }
        for item in queue.entries
    ]


def work_payload(work_items: tuple[ProjectionWorkItem, ...]) -> list[dict[str, object]]:
    return [
        {
            "key": str(item.key),
            "duration_seconds": item.duration_seconds,
            "source": item.source.value,
            "queue_entry_id": str(item.queue_entry_id) if item.queue_entry_id else None,
            "reservation_id": str(item.reservation_id) if item.reservation_id else None,
            "active_service_seconds": item.active_service_seconds,
        }
        for item in work_items
    ]


def delivery_payload(delivery: DeliveryProjectionSnapshot) -> tuple[object, object]:
    active = delivery.active_service
    activity = delivery.open_resource_activity
    active_payload = None
    if active is not None:
        active_payload = {
            "service_session_id": str(active.service_session_id),
            "queue_entry_id": str(active.queue_entry_id),
            "resource_id": str(active.resource_id),
            "location_id": str(active.location_id),
            "status": active.status,
            "actual_workload_classification_id": (
                str(active.actual_workload_classification_id)
                if active.actual_workload_classification_id
                else None
            ),
            "started_at": active.started_at.isoformat(),
            "active_service_seconds": active.active_service_seconds,
            "has_open_interruption": active.has_open_interruption,
        }
    activity_payload = None
    if activity is not None:
        activity_payload = {
            "resource_activity_id": str(activity.resource_activity_id),
            "resource_id": str(activity.resource_id),
            "location_id": str(activity.location_id) if activity.location_id else None,
            "started_at": activity.started_at.isoformat(),
            "has_known_end": activity.has_known_end,
        }
    return active_payload, activity_payload
