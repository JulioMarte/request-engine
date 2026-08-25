from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping

from request_engine.modules.queue.contracts.live_queue import (
    StaffQueueEntry,
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
                             ORDER BY admitted_at, queue_entry_id
                            """
                        ),
                        {"organization_id": organization_id, "queue_id": queue_id},
                    )
                )
                .mappings()
                .all()
            )
        return tuple(_staff_entry(row) for row in rows)

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
                            SELECT id, workload_key, display_name
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
            )
            for row in rows
        )


def _staff_entry(item: RowMapping) -> StaffQueueEntry:
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
        queue_revision=cast(int, item["queue_revision"]),
        service_revision=cast(int | None, item["service_revision"]),
    )
