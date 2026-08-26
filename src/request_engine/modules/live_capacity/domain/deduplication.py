from request_engine.modules.live_capacity.contracts.projection import ProjectionWorkItem


def deduplicate_remaining_work(
    *,
    planned: tuple[ProjectionWorkItem, ...],
    queued: tuple[ProjectionWorkItem, ...],
    active: tuple[ProjectionWorkItem, ...],
) -> tuple[ProjectionWorkItem, ...]:
    active_queue_entries = {
        item.queue_entry_id for item in active if item.queue_entry_id is not None
    }
    queued_without_active = tuple(
        item for item in queued if item.queue_entry_id not in active_queue_entries
    )
    live_reservations = {
        item.reservation_id for item in (*queued, *active) if item.reservation_id is not None
    }
    planned_without_live = tuple(
        item for item in planned if item.reservation_id not in live_reservations
    )
    return (*active, *queued_without_active, *planned_without_live)
