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
                            SELECT staff.queue_entry_id, staff.queue_id,
                                   staff.subject_party_id, staff.subject_display_name,
                                   staff.reservation_id, staff.status, staff.scheduled_at,
                                   staff.arrived_at, staff.admitted_at, staff.called_at,
                                   staff.expected_workload_key, staff.service_session_id,
                                   staff.service_status, staff.actual_resource_id,
                                   staff.actual_location_id, staff.actual_workload_key,
                                   staff.service_started_at, staff.service_completed_at,
                                   hold.hold_kind AS recall_hold_kind,
                                   hold.release_at AS recall_hold_release_at,
                                   staff.queue_revision, staff.service_revision
                              FROM request_read.live_service_staff_v1 AS staff
                              LEFT JOIN LATERAL (
                                  SELECT h.hold_kind, h.release_at
                                    FROM request_engine.queue_recall_holds AS h
                                   WHERE h.organization_id = :organization_id
                                     AND h.queue_entry_id = staff.queue_entry_id
                                     AND h.released_at IS NULL
                                     AND (
                                         h.hold_kind = 'until_customer_initiates'
                                         OR h.release_at > clock_timestamp()
                                     )
                                   LIMIT 1
                              ) AS hold ON true
                             WHERE staff.organization_id = :organization_id
                               AND staff.queue_id = :queue_id
                               AND staff.queue_entry_id IS NOT NULL
                               AND staff.status IN ('waiting','called','serving')
                             ORDER BY staff.admitted_at, staff.queue_entry_id
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
