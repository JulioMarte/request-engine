from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.queue.adapters.db.subject_authority import require_subject_authority
from request_engine.modules.queue.application.errors import QueueNotFound
from request_engine.modules.queue.contracts.service_queue import (
    QueueEntry,
    QueueEntryStatus,
    QueueStatus,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction


class PostgresServiceQueueReader:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def get_queue_status(
        self,
        organization_id: UUID,
        principal_id: UUID,
        queue_id: UUID,
        subject_party_id: UUID,
        allow_subject_override: bool,
    ) -> QueueStatus:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            await require_subject_authority(
                session,
                organization_id=organization_id,
                principal_id=principal_id,
                subject_party_id=subject_party_id,
                scope_key="queue.manage",
                allow_operator_override=allow_subject_override,
                lock_authority=False,
            )

            queue_row = (
                (
                    await session.execute(
                        text(
                            """
                        SELECT id AS queue_id, queue_key, display_name
                        FROM request_engine.service_queues
                        WHERE organization_id = :organization_id
                          AND id = :queue_id
                        """
                        ),
                        {"organization_id": organization_id, "queue_id": queue_id},
                    )
                )
                .mappings()
                .first()
            )
            if queue_row is None:
                raise QueueNotFound(queue_id)

            entry_row = (
                (
                    await session.execute(
                        text(
                            """
                        SELECT id, service_queue_id, subject_party_id, status,
                               admitted_at, called_at, revision
                        FROM request_engine.queue_entries
                        WHERE organization_id = :organization_id
                          AND service_queue_id = :queue_id
                          AND subject_party_id = :subject_party_id
                          AND status IN ('waiting', 'called', 'serving')
                        ORDER BY admitted_at DESC, id DESC
                        LIMIT 1
                        """
                        ),
                        {
                            "organization_id": organization_id,
                            "queue_id": queue_id,
                            "subject_party_id": subject_party_id,
                        },
                    )
                )
                .mappings()
                .first()
            )

            entry: QueueEntry | None = None
            entries_ahead: int | None = None
            if entry_row is not None:
                entry = QueueEntry(
                    id=cast(UUID, entry_row["id"]),
                    queue_id=cast(UUID, entry_row["service_queue_id"]),
                    subject_party_id=cast(UUID, entry_row["subject_party_id"]),
                    status=QueueEntryStatus(cast(str, entry_row["status"])),
                    admitted_at=cast(datetime, entry_row["admitted_at"]),
                    called_at=cast(datetime | None, entry_row["called_at"]),
                    revision=cast(int, entry_row["revision"]),
                )

                if entry.status is QueueEntryStatus.WAITING:
                    count_row = (
                        await session.execute(
                            text(
                                """
                                SELECT count(*)
                                  FROM request_engine.queue_entries q
                                 WHERE q.organization_id = :organization_id
                                   AND q.service_queue_id = :queue_id
                                   AND q.status = 'waiting'
                                   AND (q.admitted_at, q.id) < (:admitted_at, :entry_id)
                                   AND NOT EXISTS (
                                       SELECT 1
                                         FROM request_engine.queue_entry_recall_holds h
                                        WHERE h.organization_id = q.organization_id
                                          AND h.queue_entry_id = q.id
                                          AND h.released_at IS NULL
                                          AND (
                                              h.condition_kind <> 'until_time'
                                              OR h.until_at > clock_timestamp()
                                          )
                                   )
                                   AND NOT EXISTS (
                                       SELECT 1
                                         FROM request_engine.queue_entry_skips s
                                        WHERE s.organization_id = q.organization_id
                                          AND s.queue_entry_id = q.id
                                          AND s.consumed_at IS NULL
                                   )
                                """
                            ),
                            {
                                "organization_id": organization_id,
                                "queue_id": queue_id,
                                "admitted_at": entry.admitted_at,
                                "entry_id": entry.id,
                            },
                        )
                    ).one()
                    entries_ahead = cast(int, count_row[0])
                elif entry.status in (QueueEntryStatus.CALLED, QueueEntryStatus.SERVING):
                    entries_ahead = 0

        return QueueStatus(
            queue_id=cast(UUID, queue_row["queue_id"]),
            queue_key=cast(str, queue_row["queue_key"]),
            display_name=cast(str, queue_row["display_name"]),
            entry=entry,
            entries_ahead=entries_ahead,
        )
