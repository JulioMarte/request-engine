from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.queue.application.errors import (
    AlreadyInQueue,
    QueueEntryNotCancellable,
    QueueEntryRevisionConflict,
    QueueInactive,
    QueueNotFound,
    TenantReferenceNotUsable,
)
from request_engine.modules.queue.application.live_commands import CheckInCommand, MarkNoShowCommand
from request_engine.modules.queue.contracts.live_queue import LiveQueueEntry
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)
from request_engine.platform.outbox.postgres import append_outbox


class PostgresLiveQueueCommands:
    """Staff admission/no-show commands preserving the existing FIFO protocol."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def check_in(self, command: CheckInCommand) -> LiveQueueEntry:
        fingerprint = command_fingerprint(
            "queue.check_in",
            {
                "queue_id": command.queue_id,
                "subject_party_id": command.subject_party_id,
                "reservation_id": command.reservation_id,
                "offering_id": command.offering_id,
                "expected_workload_classification_id": command.expected_workload_classification_id,
            },
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idem, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability="queue.check_in",
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _entry_from_json(cast(dict[str, object], replay["entry"]))

            queue = await _lock_active_queue(session, command.organization_id, command.queue_id)
            await _require_active_subject(session, command.organization_id, command.subject_party_id)
            await _require_active_workload(
                session,
                command.organization_id,
                command.expected_workload_classification_id,
            )
            effective_offering_id = command.offering_id or cast(UUID | None, queue["offering_id"])
            if command.reservation_id is not None:
                reservation_offering = await _require_reservation_match(
                    session,
                    organization_id=command.organization_id,
                    reservation_id=command.reservation_id,
                    subject_party_id=command.subject_party_id,
                    queue_location_id=cast(UUID | None, queue["location_id"]),
                    queue_offering_id=cast(UUID | None, queue["offering_id"]),
                )
                if effective_offering_id is None:
                    effective_offering_id = reservation_offering
                elif effective_offering_id != reservation_offering:
                    raise TenantReferenceNotUsable("offering_id", effective_offering_id)
            elif effective_offering_id is not None:
                await _require_offering(session, command.organization_id, effective_offering_id)

            existing = (
                await session.execute(
                    text(
                        """
                        SELECT 1 FROM request_engine.queue_entries
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

            db_now = cast(
                datetime,
                (await session.execute(text("SELECT clock_timestamp()"))).scalar_one(),
            )
            row = (
                (
                    await session.execute(
                        text(
                            """
                            INSERT INTO request_engine.queue_entries (
                                organization_id, service_queue_id, subject_party_id,
                                reservation_id, offering_id, arrived_at, admitted_at,
                                expected_workload_classification_id
                            ) VALUES (
                                :organization_id, :queue_id, :subject_party_id,
                                :reservation_id, :offering_id, :arrived_at, :admitted_at,
                                :expected_workload_classification_id
                            )
                            RETURNING id, service_queue_id, subject_party_id, reservation_id,
                                      offering_id, status, arrived_at, admitted_at, called_at,
                                      expected_workload_classification_id, revision
                            """
                        ),
                        {
                            "organization_id": command.organization_id,
                            "queue_id": command.queue_id,
                            "subject_party_id": command.subject_party_id,
                            "reservation_id": command.reservation_id,
                            "offering_id": effective_offering_id,
                            "arrived_at": db_now,
                            "admitted_at": db_now,
                            "expected_workload_classification_id": command.expected_workload_classification_id,
                        },
                    )
                )
                .mappings()
                .one()
            )
            result = _entry_from_row(row)
            details: dict[str, object] = {
                "queue_id": str(command.queue_id),
                "subject_party_id": str(command.subject_party_id),
                "reservation_id": str(command.reservation_id) if command.reservation_id else None,
                "admission_kind": "reservation" if command.reservation_id else "walk_in",
            }
            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name="queue.check_in",
                aggregate_kind="QueueEntry",
                aggregate_id=result.id,
                idempotency_id=idem,
                details=details,
            )
            await append_outbox(
                session,
                organization_id=command.organization_id,
                event_type="queue.entry_checked_in.v1",
                aggregate_kind="QueueEntry",
                aggregate_id=result.id,
                payload={**details, "queue_entry_id": str(result.id), "arrived_at": result.arrived_at.isoformat()},
            )
            await complete_idempotency(session, idem, {"entry": _entry_to_json(result)})
            return result

    async def mark_no_show(self, command: MarkNoShowCommand) -> LiveQueueEntry:
        fingerprint = command_fingerprint(
            "queue.mark_no_show",
            {"queue_entry_id": command.queue_entry_id, "expected_revision": command.expected_revision},
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idem, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability="queue.mark_no_show",
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _entry_from_json(cast(dict[str, object], replay["entry"]))
            probe = (
                (
                    await session.execute(
                        text(
                            "SELECT service_queue_id FROM request_engine.queue_entries "
                            "WHERE organization_id = :organization_id AND id = :entry_id"
                        ),
                        {"organization_id": command.organization_id, "entry_id": command.queue_entry_id},
                    )
                )
                .mappings()
                .first()
            )
            if probe is None:
                raise QueueEntryNotCancellable(command.queue_entry_id, "missing")
            await _lock_active_queue(
                session, command.organization_id, cast(UUID, probe["service_queue_id"])
            )
            row = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT id, service_queue_id, subject_party_id, reservation_id,
                                   offering_id, status, arrived_at, admitted_at, called_at,
                                   expected_workload_classification_id, revision
                              FROM request_engine.queue_entries
                             WHERE organization_id = :organization_id AND id = :entry_id
                             FOR UPDATE
                            """
                        ),
                        {"organization_id": command.organization_id, "entry_id": command.queue_entry_id},
                    )
                )
                .mappings()
                .one()
            )
            actual_revision = cast(int, row["revision"])
            if actual_revision != command.expected_revision:
                raise QueueEntryRevisionConflict(
                    command.queue_entry_id, command.expected_revision, actual_revision
                )
            current = cast(str, row["status"])
            if current != "called":
                raise QueueEntryNotCancellable(command.queue_entry_id, current)
            session_exists = (
                await session.execute(
                    text(
                        "SELECT 1 FROM request_engine.service_sessions "
                        "WHERE organization_id = :organization_id AND queue_entry_id = :entry_id"
                    ),
                    {"organization_id": command.organization_id, "entry_id": command.queue_entry_id},
                )
            ).first()
            if session_exists is not None:
                raise QueueEntryNotCancellable(command.queue_entry_id, "service_session_exists")
            updated = (
                (
                    await session.execute(
                        text(
                            """
                            UPDATE request_engine.queue_entries
                               SET status = 'no_show', revision = revision + 1,
                                   updated_at = clock_timestamp()
                             WHERE organization_id = :organization_id AND id = :entry_id
                             RETURNING id, service_queue_id, subject_party_id, reservation_id,
                                       offering_id, status, arrived_at, admitted_at, called_at,
                                       expected_workload_classification_id, revision
                            """
                        ),
                        {"organization_id": command.organization_id, "entry_id": command.queue_entry_id},
                    )
                )
                .mappings()
                .one()
            )
            result = _entry_from_row(updated)
            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name="queue.mark_no_show",
                aggregate_kind="QueueEntry",
                aggregate_id=result.id,
                idempotency_id=idem,
                details={"queue_id": str(result.queue_id)},
            )
            await append_outbox(
                session,
                organization_id=command.organization_id,
                event_type="queue.entry_no_show.v1",
                aggregate_kind="QueueEntry",
                aggregate_id=result.id,
                payload={"queue_entry_id": str(result.id), "queue_id": str(result.queue_id)},
            )
            await complete_idempotency(session, idem, {"entry": _entry_to_json(result)})
            return result


async def _lock_active_queue(
    session: AsyncSession, organization_id: UUID, queue_id: UUID
) -> RowMapping:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT id, location_id, offering_id, active
                      FROM request_engine.service_queues
                     WHERE organization_id = :organization_id AND id = :queue_id
                     FOR UPDATE
                    """
                ),
                {"organization_id": organization_id, "queue_id": queue_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise QueueNotFound(queue_id)
    if row["active"] is not True:
        raise QueueInactive(queue_id)
    return row


async def _require_active_subject(session: AsyncSession, organization_id: UUID, subject_id: UUID) -> None:
    row = (
        await session.execute(
            text(
                "SELECT 1 FROM request_engine.parties "
                "WHERE organization_id = :organization_id AND id = :subject_id AND active"
            ),
            {"organization_id": organization_id, "subject_id": subject_id},
        )
    ).first()
    if row is None:
        raise TenantReferenceNotUsable("subject_party_id", subject_id)


async def _require_offering(session: AsyncSession, organization_id: UUID, offering_id: UUID) -> None:
    row = (
        await session.execute(
            text(
                "SELECT 1 FROM request_engine.offerings "
                "WHERE organization_id = :organization_id AND id = :offering_id AND active"
            ),
            {"organization_id": organization_id, "offering_id": offering_id},
        )
    ).first()
    if row is None:
        raise TenantReferenceNotUsable("offering_id", offering_id)


async def _require_active_workload(
    session: AsyncSession, organization_id: UUID, workload_id: UUID | None
) -> None:
    if workload_id is None:
        return
    row = (
        await session.execute(
            text(
                "SELECT 1 FROM request_engine.operational_workload_classifications "
                "WHERE organization_id = :organization_id AND id = :workload_id AND active"
            ),
            {"organization_id": organization_id, "workload_id": workload_id},
        )
    ).first()
    if row is None:
        raise TenantReferenceNotUsable("expected_workload_classification_id", workload_id)


async def _require_reservation_match(
    session: AsyncSession,
    *,
    organization_id: UUID,
    reservation_id: UUID,
    subject_party_id: UUID,
    queue_location_id: UUID | None,
    queue_offering_id: UUID | None,
) -> UUID:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT r.subject_party_id, r.location_id, ov.offering_id
                      FROM request_engine.reservations r
                      JOIN request_engine.offering_versions ov
                        ON ov.organization_id = r.organization_id
                       AND ov.id = r.offering_version_id
                     WHERE r.organization_id = :organization_id AND r.id = :reservation_id
                       AND r.status = 'confirmed'
                    """
                ),
                {"organization_id": organization_id, "reservation_id": reservation_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None or row["subject_party_id"] != subject_party_id:
        raise TenantReferenceNotUsable("reservation_id", reservation_id)
    if queue_location_id is not None and row["location_id"] != queue_location_id:
        raise TenantReferenceNotUsable("reservation_id", reservation_id)
    offering_id = cast(UUID, row["offering_id"])
    if queue_offering_id is not None and offering_id != queue_offering_id:
        raise TenantReferenceNotUsable("reservation_id", reservation_id)
    return offering_id


def _entry_from_row(row: RowMapping) -> LiveQueueEntry:
    return LiveQueueEntry(
        id=cast(UUID, row["id"]), queue_id=cast(UUID, row["service_queue_id"]),
        subject_party_id=cast(UUID, row["subject_party_id"]),
        reservation_id=cast(UUID | None, row["reservation_id"]),
        offering_id=cast(UUID | None, row["offering_id"]), status=cast(str, row["status"]),
        arrived_at=cast(datetime, row["arrived_at"]), admitted_at=cast(datetime, row["admitted_at"]),
        called_at=cast(datetime | None, row["called_at"]),
        expected_workload_classification_id=cast(UUID | None, row["expected_workload_classification_id"]),
        revision=cast(int, row["revision"]),
    )


def _entry_to_json(item: LiveQueueEntry) -> dict[str, object]:
    return {
        "id": str(item.id), "queue_id": str(item.queue_id),
        "subject_party_id": str(item.subject_party_id),
        "reservation_id": str(item.reservation_id) if item.reservation_id else None,
        "offering_id": str(item.offering_id) if item.offering_id else None,
        "status": item.status, "arrived_at": item.arrived_at.isoformat(),
        "admitted_at": item.admitted_at.isoformat(),
        "called_at": item.called_at.isoformat() if item.called_at else None,
        "expected_workload_classification_id": (
            str(item.expected_workload_classification_id)
            if item.expected_workload_classification_id else None
        ),
        "revision": item.revision,
    }


def _entry_from_json(data: dict[str, object]) -> LiveQueueEntry:
    return LiveQueueEntry(
        id=UUID(cast(str, data["id"])), queue_id=UUID(cast(str, data["queue_id"])),
        subject_party_id=UUID(cast(str, data["subject_party_id"])),
        reservation_id=UUID(cast(str, data["reservation_id"])) if data["reservation_id"] else None,
        offering_id=UUID(cast(str, data["offering_id"])) if data["offering_id"] else None,
        status=cast(str, data["status"]), arrived_at=datetime.fromisoformat(cast(str, data["arrived_at"])),
        admitted_at=datetime.fromisoformat(cast(str, data["admitted_at"])),
        called_at=datetime.fromisoformat(cast(str, data["called_at"])) if data["called_at"] else None,
        expected_workload_classification_id=(
            UUID(cast(str, data["expected_workload_classification_id"]))
            if data["expected_workload_classification_id"] else None
        ),
        revision=cast(int, data["revision"]),
    )
