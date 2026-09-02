import hashlib
import json
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.queue.adapters.db.subject_authority import require_subject_authority
from request_engine.modules.queue.adapters.db.tenant_references import (
    require_active_subject_party,
    require_tenant_reference,
)
from request_engine.modules.queue.adapters.db.triage_selection import (
    consume_active_skips,
    lock_next_eligible_entry,
)
from request_engine.modules.queue.application.commands.call_next import CallNextCommand
from request_engine.modules.queue.application.commands.join_queue import JoinQueueCommand
from request_engine.modules.queue.application.errors import (
    AlreadyInQueue,
    QueueInactive,
    QueueNotFound,
)
from request_engine.modules.queue.contracts.service_queue import QueueEntry, QueueEntryStatus
from request_engine.platform.db.session import SessionFactory, tenant_transaction


class PostgresServiceQueueCommands:
    """Atomic PostgreSQL implementation of FIFO queue mutation capabilities."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def join_queue(self, command: JoinQueueCommand) -> QueueEntry:
        fingerprint = _command_fingerprint(
            "queue.join",
            {
                "queue_id": command.queue_id,
                "subject_party_id": command.subject_party_id,
                "reservation_id": command.reservation_id,
                "offering_id": command.offering_id,
            },
        )

        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idempotency_id, replay_data = await _acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability="queue.join",
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay_data is not None:
                return _queue_entry_from_json(cast(dict[str, object], replay_data["entry"]))

            await require_active_subject_party(
                session,
                organization_id=command.organization_id,
                subject_party_id=command.subject_party_id,
            )
            await require_tenant_reference(
                session,
                organization_id=command.organization_id,
                table_name="reservations",
                reference_kind="reservation_id",
                reference_id=command.reservation_id,
            )
            await require_tenant_reference(
                session,
                organization_id=command.organization_id,
                table_name="offerings",
                reference_kind="offering_id",
                reference_id=command.offering_id,
            )
            authority = await require_subject_authority(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                subject_party_id=command.subject_party_id,
                scope_key="queue.join",
                allow_operator_override=command.allow_subject_override,
            )

            await _lock_active_queue(session, command.organization_id, command.queue_id)

            existing = (
                await session.execute(
                    text(
                        """
                        SELECT id
                        FROM request_engine.queue_entries
                        WHERE organization_id = :organization_id
                          AND service_queue_id = :queue_id
                          AND subject_party_id = :subject_party_id
                          AND status IN ('waiting', 'called', 'serving')
                        LIMIT 1
                        """
                    ),
                    {
                        "organization_id": command.organization_id,
                        "queue_id": command.queue_id,
                        "subject_party_id": command.subject_party_id,
                    },
                )
            ).first()
            if existing is not None:
                raise AlreadyInQueue(command.queue_id, command.subject_party_id)

            row = (
                (
                    await session.execute(
                        text(
                            """
                        INSERT INTO request_engine.queue_entries (
                            organization_id, service_queue_id, subject_party_id,
                            reservation_id, offering_id, arrived_at, admitted_at
                        )
                        SELECT :organization_id, :queue_id, :subject_party_id,
                               :reservation_id, :offering_id, transition.at, transition.at
                          FROM (SELECT clock_timestamp() AS at) AS transition
                        RETURNING id, service_queue_id, subject_party_id, status,
                                  admitted_at, called_at, revision
                        """
                        ),
                        {
                            "organization_id": command.organization_id,
                            "queue_id": command.queue_id,
                            "subject_party_id": command.subject_party_id,
                            "reservation_id": command.reservation_id,
                            "offering_id": command.offering_id,
                        },
                    )
                )
                .mappings()
                .one()
            )
            entry = _queue_entry_from_row(row)

            await _append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name="queue.join",
                aggregate_id=entry.id,
                details={
                    "queue_id": str(command.queue_id),
                    "subject_party_id": str(command.subject_party_id),
                    "subject_authority": authority.audit_details(),
                },
                idempotency_id=idempotency_id,
            )
            await _complete_idempotency(
                session,
                idempotency_id,
                {"entry": _queue_entry_to_json(entry)},
            )
            return entry

    async def call_next(self, command: CallNextCommand) -> QueueEntry | None:
        fingerprint = _command_fingerprint(
            "queue.call_next",
            {"queue_id": command.queue_id},
        )

        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idempotency_id, replay_data = await _acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability="queue.call_next",
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay_data is not None:
                replay_entry = replay_data.get("entry")
                if replay_entry is None:
                    return None
                return _queue_entry_from_json(cast(dict[str, object], replay_entry))

            await _lock_active_queue(session, command.organization_id, command.queue_id)
            entry_id = await lock_next_eligible_entry(
                session,
                command.organization_id,
                command.queue_id,
            )
            if entry_id is None:
                await _complete_idempotency(session, idempotency_id, {"entry": None})
                return None

            await consume_active_skips(
                session,
                command.organization_id,
                command.queue_id,
                entry_id,
            )
            row = (
                (
                    await session.execute(
                        text(
                            """
                        UPDATE request_engine.queue_entries
                        SET status = 'called',
                            called_at = clock_timestamp(),
                            revision = revision + 1
                        WHERE organization_id = :organization_id
                          AND id = :entry_id
                          AND status = 'waiting'
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
            entry = _queue_entry_from_row(row)

            await _append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name="queue.call_next",
                aggregate_id=entry.id,
                details={"queue_id": str(command.queue_id)},
                idempotency_id=idempotency_id,
            )
            await session.execute(
                text(
                    """
                    INSERT INTO request_engine.outbox_messages (
                        organization_id,
                        event_type,
                        schema_version,
                        aggregate_kind,
                        aggregate_id,
                        payload
                    ) VALUES (
                        :organization_id,
                        'queue.entry_called.v1',
                        1,
                        'QueueEntry',
                        :entry_id,
                        CAST(:payload AS jsonb)
                    )
                    """
                ),
                {
                    "organization_id": command.organization_id,
                    "entry_id": entry.id,
                    "payload": json.dumps(
                        {
                            "queue_entry_id": str(entry.id),
                            "queue_id": str(entry.queue_id),
                            "subject_party_id": str(entry.subject_party_id),
                            "called_at": (entry.called_at.isoformat() if entry.called_at else None),
                        },
                        separators=(",", ":"),
                    ),
                },
            )
            await _complete_idempotency(
                session,
                idempotency_id,
                {"entry": _queue_entry_to_json(entry)},
            )
            return entry


async def _lock_active_queue(
    session: AsyncSession,
    organization_id: UUID,
    queue_id: UUID,
) -> None:
    row = (
        await session.execute(
            text(
                """
                SELECT active
                FROM request_engine.service_queues
                WHERE organization_id = :organization_id
                  AND id = :queue_id
                FOR UPDATE
                """
            ),
            {"organization_id": organization_id, "queue_id": queue_id},
        )
    ).first()
    if row is None:
        raise QueueNotFound(queue_id)
    if row[0] is not True:
        raise QueueInactive(queue_id)


async def _acquire_idempotency(
    session: AsyncSession,
    *,
    organization_id: UUID,
    principal_id: UUID,
    capability: str,
    idempotency_key: str,
    fingerprint: str,
) -> tuple[UUID, dict[str, object] | None]:
    row = (
        (
            await session.execute(
                text(
                    """
                SELECT idempotency_id, status, result_data, replay
                FROM request_cmd.acquire_idempotency(
                    :organization_id,
                    :principal_id,
                    :capability,
                    :idempotency_key,
                    :fingerprint
                )
                """
                ),
                {
                    "organization_id": organization_id,
                    "principal_id": principal_id,
                    "capability": capability,
                    "idempotency_key": idempotency_key,
                    "fingerprint": fingerprint,
                },
            )
        )
        .mappings()
        .one()
    )

    idempotency_id = cast(UUID, row["idempotency_id"])
    if cast(bool, row["replay"]):
        return idempotency_id, cast(dict[str, object], row["result_data"])
    return idempotency_id, None


async def _complete_idempotency(
    session: AsyncSession,
    idempotency_id: UUID,
    result: dict[str, object],
) -> None:
    row = (
        await session.execute(
            text(
                """
                SELECT request_cmd.complete_idempotency(
                    :idempotency_id,
                    CAST(:result AS jsonb)
                )
                """
            ),
            {
                "idempotency_id": idempotency_id,
                "result": json.dumps(result, separators=(",", ":")),
            },
        )
    ).one()
    if row[0] is not True:
        raise RuntimeError(f"idempotency record {idempotency_id} could not be completed")


async def _append_audit(
    session: AsyncSession,
    *,
    organization_id: UUID,
    principal_id: UUID,
    command_name: str,
    aggregate_id: UUID,
    details: dict[str, object],
    idempotency_id: UUID,
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO request_engine.audit_records (
                organization_id,
                actor_principal_id,
                command_name,
                aggregate_kind,
                aggregate_id,
                idempotency_record_id,
                details
            ) VALUES (
                :organization_id,
                :principal_id,
                :command_name,
                'QueueEntry',
                :aggregate_id,
                :idempotency_id,
                CAST(:details AS jsonb)
            )
            """
        ),
        {
            "organization_id": organization_id,
            "principal_id": principal_id,
            "command_name": command_name,
            "aggregate_id": aggregate_id,
            "idempotency_id": idempotency_id,
            "details": json.dumps(details, separators=(",", ":")),
        },
    )


def _command_fingerprint(capability: str, values: dict[str, object]) -> str:
    canonical = json.dumps(
        {"capability": capability, **values},
        default=str,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _queue_entry_from_row(row: RowMapping) -> QueueEntry:
    return QueueEntry(
        id=cast(UUID, row["id"]),
        queue_id=cast(UUID, row["service_queue_id"]),
        subject_party_id=cast(UUID, row["subject_party_id"]),
        status=QueueEntryStatus(cast(str, row["status"])),
        admitted_at=cast(datetime, row["admitted_at"]),
        called_at=cast(datetime | None, row["called_at"]),
        revision=cast(int, row["revision"]),
    )


def _queue_entry_to_json(entry: QueueEntry) -> dict[str, object]:
    return {
        "id": str(entry.id),
        "queue_id": str(entry.queue_id),
        "subject_party_id": str(entry.subject_party_id),
        "status": entry.status.value,
        "admitted_at": entry.admitted_at.isoformat(),
        "called_at": entry.called_at.isoformat() if entry.called_at else None,
        "revision": entry.revision,
    }


def _queue_entry_from_json(data: dict[str, object]) -> QueueEntry:
    called_at = cast(str | None, data["called_at"])
    return QueueEntry(
        id=UUID(cast(str, data["id"])),
        queue_id=UUID(cast(str, data["queue_id"])),
        subject_party_id=UUID(cast(str, data["subject_party_id"])),
        status=QueueEntryStatus(cast(str, data["status"])),
        admitted_at=datetime.fromisoformat(cast(str, data["admitted_at"])),
        called_at=datetime.fromisoformat(called_at) if called_at else None,
        revision=cast(int, data["revision"]),
    )
