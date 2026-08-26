from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.queue.adapters.db.live_capacity_customer_source import (
    read_customer_projection_target,
)
from request_engine.modules.queue.contracts.live_capacity import (
    CustomerQueueProjectionTarget,
    QueueProjectionEntry,
    QueueProjectionSnapshot,
)
from request_engine.platform.db.read_snapshot import postgres_snapshot_session
from request_engine.platform.db.read_snapshot_types import ReadSnapshot


class PostgresQueueProjectionSource:
    async def read_projection_queue(
        self,
        snapshot: ReadSnapshot,
        *,
        organization_id: UUID,
        queue_id: UUID,
        observed_at: datetime,
        relevant_reservation_ids: tuple[UUID, ...] = (),
    ) -> QueueProjectionSnapshot:
        session = postgres_snapshot_session(snapshot)
        rows = (
            (
                await session.execute(
                    text(
                        """
                        SELECT id AS queue_entry_id,
                               service_queue_id AS queue_id,
                               reservation_id,
                               status,
                               arrived_at,
                               admitted_at,
                               called_at,
                               expected_workload_classification_id
                        FROM request_engine.queue_entries
                        WHERE organization_id = :organization_id
                          AND service_queue_id = :queue_id
                          AND status IN ('waiting','called','serving')
                        ORDER BY admitted_at, id
                        """
                    ),
                    {"organization_id": organization_id, "queue_id": queue_id},
                )
            )
            .mappings()
            .all()
        )
        completed = frozenset[UUID]()
        if relevant_reservation_ids:
            completed_rows = (
                await session.execute(
                    text(
                        """
                        SELECT DISTINCT reservation_id
                        FROM request_engine.queue_entries
                        WHERE organization_id = :organization_id
                          AND service_queue_id = :queue_id
                          AND status = 'completed'
                          AND reservation_id = ANY(CAST(:reservation_ids AS uuid[]))
                        """
                    ),
                    {
                        "organization_id": organization_id,
                        "queue_id": queue_id,
                        "reservation_ids": list(relevant_reservation_ids),
                    },
                )
            ).scalars()
            completed = frozenset(cast(UUID, value) for value in completed_rows)
        return QueueProjectionSnapshot(
            queue_id=queue_id,
            observed_at=observed_at,
            entries=tuple(
                QueueProjectionEntry(
                    queue_entry_id=cast(UUID, row["queue_entry_id"]),
                    queue_id=cast(UUID, row["queue_id"]),
                    reservation_id=cast(UUID | None, row["reservation_id"]),
                    status=cast(str, row["status"]),
                    arrived_at=cast(datetime, row["arrived_at"]),
                    admitted_at=cast(datetime, row["admitted_at"]),
                    called_at=cast(datetime | None, row["called_at"]),
                    expected_workload_classification_id=cast(
                        UUID | None, row["expected_workload_classification_id"]
                    ),
                )
                for row in rows
            ),
            completed_reservation_ids=completed,
        )

    async def read_customer_projection_target(
        self,
        snapshot: ReadSnapshot,
        *,
        organization_id: UUID,
        principal_id: UUID,
        queue_id: UUID,
        subject_party_id: UUID,
        allow_subject_override: bool,
    ) -> CustomerQueueProjectionTarget | None:
        return await read_customer_projection_target(
            snapshot,
            organization_id=organization_id,
            principal_id=principal_id,
            queue_id=queue_id,
            subject_party_id=subject_party_id,
            allow_subject_override=allow_subject_override,
        )
