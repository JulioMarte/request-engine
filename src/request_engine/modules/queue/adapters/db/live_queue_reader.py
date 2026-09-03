from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.queue.adapters.db.live_queue_history_reader import (
    read_staff_queue_history,
)
from request_engine.modules.queue.adapters.db.live_queue_mapping import staff_entry_from_row
from request_engine.modules.queue.contracts.live_queue import (
    StaffQueueEntry,
    StaffQueueHistoryPage,
    WorkloadClassification,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction


class PostgresLiveQueueReader:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def staff_queue(
        self,
        organization_id: UUID,
        queue_id: UUID,
    ) -> tuple[StaffQueueEntry, ...]:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            rows = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT v.queue_entry_id, v.queue_id, v.subject_party_id,
                                   v.subject_display_name, v.reservation_id, v.status,
                                   v.scheduled_at, v.arrived_at, v.admitted_at, v.called_at,
                                   v.expected_workload_key, v.service_session_id,
                                   v.service_status, v.actual_resource_id,
                                   v.actual_location_id, v.actual_workload_key,
                                   v.service_started_at, v.service_completed_at,
                                   (h.id IS NULL AND s.id IS NULL) AS recall_eligible,
                                   h.id AS recall_hold_id,
                                   h.condition_kind AS recall_hold_kind,
                                   h.until_at AS recall_hold_until_at,
                                   h.event_key AS recall_hold_event_key,
                                   h.reason AS recall_hold_reason,
                                   s.reason AS active_skip_reason,
                                   v.queue_revision, v.service_revision
                              FROM request_read.live_service_staff_v1 v
                              LEFT JOIN LATERAL (
                                  SELECT id, condition_kind, until_at, event_key, reason
                                    FROM request_engine.queue_entry_recall_holds
                                   WHERE organization_id = v.organization_id
                                     AND queue_entry_id = v.queue_entry_id
                                     AND released_at IS NULL
                                     AND (
                                         condition_kind <> 'until_time'
                                         OR until_at > clock_timestamp()
                                     )
                                   ORDER BY created_at DESC, id DESC
                                   LIMIT 1
                              ) h ON TRUE
                              LEFT JOIN LATERAL (
                                  SELECT id, reason
                                    FROM request_engine.queue_entry_skips
                                   WHERE organization_id = v.organization_id
                                     AND queue_entry_id = v.queue_entry_id
                                     AND consumed_at IS NULL
                                   ORDER BY created_at DESC, id DESC
                                   LIMIT 1
                              ) s ON TRUE
                             WHERE v.organization_id = :organization_id
                               AND v.queue_id = :queue_id
                               AND v.queue_entry_id IS NOT NULL
                               AND v.status IN ('waiting','called','serving')
                             ORDER BY v.admitted_at, v.queue_entry_id
                            """
                        ),
                        {"organization_id": organization_id, "queue_id": queue_id},
                    )
                )
                .mappings()
                .all()
            )
        return tuple(staff_entry_from_row(row) for row in rows)

    async def staff_queue_history(
        self,
        organization_id: UUID,
        queue_id: UUID,
        *,
        window_start: datetime,
        window_end: datetime,
        limit: int,
        cursor: UUID | None,
    ) -> StaffQueueHistoryPage:
        return await read_staff_queue_history(
            self._session_factory,
            organization_id,
            queue_id,
            window_start=window_start,
            window_end=window_end,
            limit=limit,
            cursor=cursor,
        )

    async def workloads(
        self,
        organization_id: UUID,
    ) -> tuple[WorkloadClassification, ...]:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            rows = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT id, workload_key, display_name, active, revision
                              FROM request_engine.operational_workload_classifications
                             WHERE organization_id = :organization_id AND active
                             ORDER BY workload_key, id
                            """
                        ),
                        {"organization_id": organization_id},
                    )
                )
                .mappings()
                .all()
            )
        return tuple(
            WorkloadClassification(
                id=cast(UUID, row["id"]),
                workload_key=cast(str, row["workload_key"]),
                display_name=cast(str, row["display_name"]),
                active=cast(bool, row["active"]),
                revision=cast(int, row["revision"]),
            )
            for row in rows
        )
