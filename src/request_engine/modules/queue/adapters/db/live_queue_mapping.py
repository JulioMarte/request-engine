from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy.engine import RowMapping

from request_engine.modules.queue.contracts.live_queue import StaffQueueEntry


def staff_entry_from_row(item: RowMapping) -> StaffQueueEntry:
    return StaffQueueEntry(
        queue_entry_id=cast(UUID, item["queue_entry_id"]),
        queue_id=cast(UUID, item["queue_id"]),
        subject_party_id=cast(UUID, item["subject_party_id"]),
        subject_display_name=cast(str, item["subject_display_name"]),
        reservation_id=cast(UUID | None, item["reservation_id"]),
        status=cast(str, item["status"]),
        scheduled_at=cast(datetime | None, item["scheduled_at"]),
        arrived_at=cast(datetime, item["arrived_at"]),
        admitted_at=cast(datetime, item["admitted_at"]),
        called_at=cast(datetime | None, item["called_at"]),
        expected_workload_key=cast(str | None, item["expected_workload_key"]),
        service_session_id=cast(UUID | None, item["service_session_id"]),
        service_status=cast(str | None, item["service_status"]),
        actual_resource_id=cast(UUID | None, item["actual_resource_id"]),
        actual_location_id=cast(UUID | None, item["actual_location_id"]),
        actual_workload_key=cast(str | None, item["actual_workload_key"]),
        service_started_at=cast(datetime | None, item["service_started_at"]),
        service_completed_at=cast(datetime | None, item["service_completed_at"]),
        recall_hold_kind=cast(str | None, item["recall_hold_kind"]),
        recall_hold_release_at=cast(datetime | None, item["recall_hold_release_at"]),
        queue_revision=cast(int, item["queue_revision"]),
        service_revision=cast(int | None, item["service_revision"]),
    )
