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
                            SELECT queue_entry_id, queue_id, subject_party_id,
                                   subject_display_name, reservation_id, status,
                                   scheduled_at, arrived_at, admitted_at, called_at,
                                   expected_workload_key, service_session_id,
                                   service_status, actual_resource_id,
                                   actual_location_id, actual_workload_key,
                                   service_started_at, service_completed_at,
                                   queue_revision, service_revision
                              FROM request_read.live_service_staff_v1
                             WHERE organization_id = :organization_id
                               AND queue_id = :queue_id
                               AND queue_entry_id IS NOT NULL
                               AND status IN ('waiting','called','serving')
                             ORDER BY admitted_at, queue_entry_id
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
