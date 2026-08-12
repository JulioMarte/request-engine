from typing import cast
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.queue.adapters.db.service_queue_commands import (
    _queue_entry_from_json,
    _queue_entry_from_row,
    _queue_entry_to_json,
)
from request_engine.modules.queue.application.commands.leave_queue import LeaveQueueCommand
from request_engine.modules.queue.application.errors import (
    ActiveQueueEntryNotFound,
    QueueEntryNotCancellable,
    QueueNotFound,
)
from request_engine.modules.queue.contracts.service_queue import QueueEntry
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)
from request_engine.platform.outbox.postgres import append_outbox


class PostgresLeaveQueueCommands:
    """Cancel a waiting/called queue entry while preserving serving work."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def leave_queue(self, command: LeaveQueueCommand) -> QueueEntry:
        capability = "queue.leave"
        fingerprint = command_fingerprint(
            capability,
            {
                "queue_id": command.queue_id,
                "subject_party_id": command.subject_party_id,
                "reason": command.reason,
            },
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability=capability,
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                raw_entry = replay.get("entry")
                if not isinstance(raw_entry, dict):
                    raise RuntimeError("completed queue.leave replay has no entry")
                return _queue_entry_from_json(cast(dict[str, object], raw_entry))

            queue_exists = (
                await session.execute(
                    text(
                        """
                        SELECT 1
                        FROM request_engine.service_queues
                        WHERE organization_id = :organization_id
                          AND id = :queue_id
                        FOR UPDATE
                        """
                    ),
                    {
                        "organization_id": command.organization_id,
                        "queue_id": command.queue_id,
                    },
                )
            ).first()
            if queue_exists is None:
                raise QueueNotFound(command.queue_id)

            row = (
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
                            FOR UPDATE
                            """
                        ),
                        {
                            "organization_id": command.organization_id,
                            "queue_id": command.queue_id,
                            "subject_party_id": command.subject_party_id,
                        },
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise ActiveQueueEntryNotFound(command.queue_id, command.subject_party_id)
            status = cast(str, row["status"])
            entry_id = cast(UUID, row["id"])
            if status not in ("waiting", "called"):
                raise QueueEntryNotCancellable(entry_id, status)

            updated = (
                (
                    await session.execute(
                        text(
                            """
                            UPDATE request_engine.queue_entries
                            SET status = 'cancelled',
                                revision = revision + 1,
                                updated_at = clock_timestamp()
                            WHERE organization_id = :organization_id
                              AND id = :entry_id
                            RETURNING id, service_queue_id, subject_party_id, status,
                                      admitted_at, called_at, revision
                            """
                        ),
                        {
                            "organization_id": command.organization_id,
                            "entry_id": entry_id,
                        },
                    )
                )
                .mappings()
                .one()
            )
            entry = _queue_entry_from_row(updated)
            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name=capability,
                aggregate_kind="QueueEntry",
                aggregate_id=entry.id,
                idempotency_id=idempotency_id,
                details={
                    "queue_id": str(command.queue_id),
                    "subject_party_id": str(command.subject_party_id),
                    "reason": command.reason,
                },
            )
            await append_outbox(
                session,
                organization_id=command.organization_id,
                event_type="queue.entry_cancelled.v1",
                aggregate_kind="QueueEntry",
                aggregate_id=entry.id,
                payload={
                    "queue_entry_id": str(entry.id),
                    "queue_id": str(entry.queue_id),
                    "subject_party_id": str(entry.subject_party_id),
                    "reason": command.reason,
                },
            )
            await complete_idempotency(
                session,
                idempotency_id,
                {"entry": _queue_entry_to_json(entry)},
            )
            return entry
