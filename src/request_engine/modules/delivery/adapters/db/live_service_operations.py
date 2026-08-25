from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.delivery.application.errors import (
    LiveServiceRevisionConflict,
    QueueEntryNotCallable,
    ResourceActivityNotFound,
    ResourceExecutionUnavailable,
    ServiceSessionNotActionable,
    ServiceSessionNotFound,
)
from request_engine.modules.delivery.application.resource_activity_commands import (
    EndResourceActivityCommand,
    StartResourceActivityCommand,
)
from request_engine.modules.delivery.application.service_session_commands import (
    CompleteServiceCommand,
    PauseServiceCommand,
    ResumeServiceCommand,
    StartServiceCommand,
)
from request_engine.modules.delivery.contracts.service_session import (
    ResourceActivity,
    ResourceActivityKind,
    ServiceSession,
    ServiceSessionStatus,
)
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)
from request_engine.platform.outbox.postgres import append_outbox


class PostgresLiveServiceOperations:
    """F3 Queue↔Delivery operations inside one PostgreSQL transaction."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def start_service(self, command: StartServiceCommand) -> ServiceSession:
        fingerprint = command_fingerprint(
            "service_session.start",
            {
                "queue_entry_id": command.queue_entry_id,
                "resource_id": command.resource_id,
                "location_id": command.location_id,
                "expected_queue_revision": command.expected_queue_revision,
                "actual_workload_classification_id": command.actual_workload_classification_id,
            },
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idem, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability="service_session.start",
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _session_from_json(cast(dict[str, object], replay["session"]))

            probe = await _probe_queue_entry(session, command.organization_id, command.queue_entry_id)
            await _lock_queue(session, command.organization_id, cast(UUID, probe["service_queue_id"]))
            entry = await _lock_queue_entry(session, command.organization_id, command.queue_entry_id)
            _require_revision(entry, command.queue_entry_id, command.expected_queue_revision)
            entry_status = cast(str, entry["status"])
            if entry_status != "called":
                raise QueueEntryNotCallable(command.queue_entry_id, entry_status)

            await _lock_resource(session, command.organization_id, command.resource_id)
            db_now = await _db_now(session)
            await _require_execution_assignment(
                session,
                organization_id=command.organization_id,
                resource_id=command.resource_id,
                location_id=command.location_id,
                at=db_now,
            )
            await _require_workload(
                session,
                command.organization_id,
                command.actual_workload_classification_id,
            )

            row = (
                (
                    await session.execute(
                        text(
                            """
                            INSERT INTO request_engine.service_sessions (
                                organization_id, queue_entry_id, resource_id, location_id,
                                actual_workload_classification_id, started_at
                            ) VALUES (
                                :organization_id, :queue_entry_id, :resource_id, :location_id,
                                :actual_workload_classification_id, :started_at
                            )
                            RETURNING id, queue_entry_id, resource_id, location_id,
                                      actual_workload_classification_id, status,
                                      started_at, completed_at, revision
                            """
                        ),
                        {
                            "organization_id": command.organization_id,
                            "queue_entry_id": command.queue_entry_id,
                            "resource_id": command.resource_id,
                            "location_id": command.location_id,
                            "actual_workload_classification_id": command.actual_workload_classification_id,
                            "started_at": db_now,
                        },
                    )
                )
                .mappings()
                .one()
            )
            result = _session_from_row(row)
            await session.execute(
                text(
                    """
                    UPDATE request_engine.queue_entries
                       SET status = 'serving', service_started_at = :started_at,
                           completed_at = NULL, revision = revision + 1,
                           updated_at = clock_timestamp()
                     WHERE organization_id = :organization_id AND id = :queue_entry_id
                    """
                ),
                {
                    "organization_id": command.organization_id,
                    "queue_entry_id": command.queue_entry_id,
                    "started_at": result.started_at,
                },
            )
            await _record(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                idempotency_id=idem,
                command_name="service_session.start",
                aggregate_kind="ServiceSession",
                aggregate_id=result.id,
                event_type="service_session.started.v1",
                payload=_session_to_json(result),
            )
            await complete_idempotency(session, idem, {"session": _session_to_json(result)})
            return result

    async def pause_service(self, command: PauseServiceCommand) -> ServiceSession:
        return await self._change_session(
            command=command,
            capability="service_session.pause",
            expected_status="active",
            next_status="paused",
            event_type="service_session.paused.v1",
            interruption_kind=command.kind.value,
        )

    async def resume_service(self, command: ResumeServiceCommand) -> ServiceSession:
        return await self._change_session(
            command=command,
            capability="service_session.resume",
            expected_status="paused",
            next_status="active",
            event_type="service_session.resumed.v1",
            interruption_kind=None,
        )

    async def complete_service(self, command: CompleteServiceCommand) -> ServiceSession:
        fingerprint = command_fingerprint(
            "service_session.complete",
            {
                "service_session_id": command.service_session_id,
                "expected_revision": command.expected_revision,
                "actual_workload_classification_id": command.actual_workload_classification_id,
            },
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idem, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability="service_session.complete",
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _session_from_json(cast(dict[str, object], replay["session"]))

            entry, locked = await _lock_session_context(
                session, command.organization_id, command.service_session_id
            )
            _require_revision(locked, command.service_session_id, command.expected_revision)
            current = cast(str, locked["status"])
            if current != "active":
                raise ServiceSessionNotActionable(command.service_session_id, current, "complete")
            if cast(str, entry["status"]) != "serving":
                raise ServiceSessionNotActionable(
                    command.service_session_id, current, "complete with non-serving QueueEntry"
                )
            await _require_workload(
                session,
                command.organization_id,
                command.actual_workload_classification_id,
            )
            db_now = await _db_now(session)
            row = (
                (
                    await session.execute(
                        text(
                            """
                            UPDATE request_engine.service_sessions
                               SET status = 'completed', completed_at = :completed_at,
                                   actual_workload_classification_id = COALESCE(
                                      :actual_workload_classification_id,
                                      actual_workload_classification_id
                                   ),
                                   revision = revision + 1, updated_at = clock_timestamp()
                             WHERE organization_id = :organization_id AND id = :session_id
                             RETURNING id, queue_entry_id, resource_id, location_id,
                                       actual_workload_classification_id, status,
                                       started_at, completed_at, revision
                            """
                        ),
                        {
                            "organization_id": command.organization_id,
                            "session_id": command.service_session_id,
                            "completed_at": db_now,
                            "actual_workload_classification_id": command.actual_workload_classification_id,
                        },
                    )
                )
                .mappings()
                .one()
            )
            result = _session_from_row(row)
            await session.execute(
                text(
                    """
                    UPDATE request_engine.queue_entries
                       SET status = 'completed', completed_at = :completed_at,
                           revision = revision + 1, updated_at = clock_timestamp()
                     WHERE organization_id = :organization_id AND id = :queue_entry_id
                    """
                ),
                {
                    "organization_id": command.organization_id,
                    "queue_entry_id": result.queue_entry_id,
                    "completed_at": result.completed_at,
                },
            )
            await _record(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                idempotency_id=idem,
                command_name="service_session.complete",
                aggregate_kind="ServiceSession",
                aggregate_id=result.id,
                event_type="service_session.completed.v1",
                payload=_session_to_json(result),
            )
            await complete_idempotency(session, idem, {"session": _session_to_json(result)})
            return result

    async def _change_session(
        self,
        *,
        command: PauseServiceCommand | ResumeServiceCommand,
        capability: str,
        expected_status: str,
        next_status: str,
        event_type: str,
        interruption_kind: str | None,
    ) -> ServiceSession:
        fingerprint = command_fingerprint(
            capability,
            {
                "service_session_id": command.service_session_id,
                "expected_revision": command.expected_revision,
                "kind": interruption_kind,
            },
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idem, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability=capability,
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _session_from_json(cast(dict[str, object], replay["session"]))
            _, locked = await _lock_session_context(
                session, command.organization_id, command.service_session_id
            )
            _require_revision(locked, command.service_session_id, command.expected_revision)
            current = cast(str, locked["status"])
            if current != expected_status:
                raise ServiceSessionNotActionable(command.service_session_id, current, capability)
            db_now = await _db_now(session)
            if next_status == "paused":
                assert interruption_kind is not None
                await session.execute(
                    text(
                        """
                        INSERT INTO request_engine.service_session_interruptions (
                            organization_id, service_session_id, kind, started_at,
                            started_by_principal_id
                        ) VALUES (
                            :organization_id, :session_id, :kind, :started_at, :principal_id
                        )
                        """
                    ),
                    {
                        "organization_id": command.organization_id,
                        "session_id": command.service_session_id,
                        "kind": interruption_kind,
                        "started_at": db_now,
                        "principal_id": command.principal_id,
                    },
                )
            else:
                ended = await session.execute(
                    text(
                        """
                        UPDATE request_engine.service_session_interruptions
                           SET ended_at = :ended_at, ended_by_principal_id = :principal_id
                         WHERE organization_id = :organization_id
                           AND service_session_id = :session_id AND ended_at IS NULL
                         RETURNING id
                        """
                    ),
                    {
                        "organization_id": command.organization_id,
                        "session_id": command.service_session_id,
                        "ended_at": db_now,
                        "principal_id": command.principal_id,
                    },
                )
                if ended.first() is None:
                    raise ServiceSessionNotActionable(
                        command.service_session_id, current, "resume without open interruption"
                    )
            row = (
                (
                    await session.execute(
                        text(
                            """
                            UPDATE request_engine.service_sessions
                               SET status = :next_status, revision = revision + 1,
                                   updated_at = clock_timestamp()
                             WHERE organization_id = :organization_id AND id = :session_id
                             RETURNING id, queue_entry_id, resource_id, location_id,
                                       actual_workload_classification_id, status,
                                       started_at, completed_at, revision
                            """
                        ),
                        {
                            "organization_id": command.organization_id,
                            "session_id": command.service_session_id,
                            "next_status": next_status,
                        },
                    )
                )
                .mappings()
                .one()
            )
            result = _session_from_row(row)
            await _record(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                idempotency_id=idem,
                command_name=capability,
                aggregate_kind="ServiceSession",
                aggregate_id=result.id,
                event_type=event_type,
                payload={**_session_to_json(result), "transitioned_at": db_now.isoformat()},
            )
            await complete_idempotency(session, idem, {"session": _session_to_json(result)})
            return result

    async def start_resource_activity(
        self, command: StartResourceActivityCommand
    ) -> ResourceActivity:
        fingerprint = command_fingerprint(
            "resource_activity.start",
            {
                "resource_id": command.resource_id,
                "location_id": command.location_id,
                "kind": command.kind.value,
            },
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idem, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability="resource_activity.start",
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _activity_from_json(cast(dict[str, object], replay["activity"]))
            await _lock_resource(session, command.organization_id, command.resource_id)
            db_now = await _db_now(session)
            if command.location_id is not None:
                await _require_execution_assignment(
                    session,
                    organization_id=command.organization_id,
                    resource_id=command.resource_id,
                    location_id=command.location_id,
                    at=db_now,
                )
            row = (
                (
                    await session.execute(
                        text(
                            """
                            INSERT INTO request_engine.resource_activities (
                                organization_id, resource_id, location_id, activity_kind,
                                started_at, started_by_principal_id
                            ) VALUES (
                                :organization_id, :resource_id, :location_id, :kind,
                                :started_at, :principal_id
                            )
                            RETURNING id, resource_id, location_id, activity_kind,
                                      started_at, ended_at, revision
                            """
                        ),
                        {
                            "organization_id": command.organization_id,
                            "resource_id": command.resource_id,
                            "location_id": command.location_id,
                            "kind": command.kind.value,
                            "started_at": db_now,
                            "principal_id": command.principal_id,
                        },
                    )
                )
                .mappings()
                .one()
            )
            result = _activity_from_row(row)
            await _record(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                idempotency_id=idem,
                command_name="resource_activity.start",
                aggregate_kind="ResourceActivity",
                aggregate_id=result.id,
                event_type="resource_activity.started.v1",
                payload=_activity_to_json(result),
            )
            await complete_idempotency(session, idem, {"activity": _activity_to_json(result)})
            return result

    async def end_resource_activity(
        self, command: EndResourceActivityCommand
    ) -> ResourceActivity:
        fingerprint = command_fingerprint(
            "resource_activity.end",
            {
                "resource_activity_id": command.resource_activity_id,
                "expected_revision": command.expected_revision,
            },
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idem, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability="resource_activity.end",
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _activity_from_json(cast(dict[str, object], replay["activity"]))
            probe = (
                (
                    await session.execute(
                        text(
                            "SELECT resource_id FROM request_engine.resource_activities "
                            "WHERE organization_id = :organization_id AND id = :activity_id"
                        ),
                        {
                            "organization_id": command.organization_id,
                            "activity_id": command.resource_activity_id,
                        },
                    )
                )
                .mappings()
                .first()
            )
            if probe is None:
                raise ResourceActivityNotFound(command.resource_activity_id)
            await _lock_resource(session, command.organization_id, cast(UUID, probe["resource_id"]))
            row = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT id, resource_id, location_id, activity_kind,
                                   started_at, ended_at, revision
                              FROM request_engine.resource_activities
                             WHERE organization_id = :organization_id AND id = :activity_id
                             FOR UPDATE
                            """
                        ),
                        {
                            "organization_id": command.organization_id,
                            "activity_id": command.resource_activity_id,
                        },
                    )
                )
                .mappings()
                .one()
            )
            _require_revision(row, command.resource_activity_id, command.expected_revision)
            if row["ended_at"] is not None:
                raise ResourceExecutionUnavailable(cast(UUID, row["resource_id"]), "activity_already_ended")
            db_now = await _db_now(session)
            updated = (
                (
                    await session.execute(
                        text(
                            """
                            UPDATE request_engine.resource_activities
                               SET ended_at = :ended_at, ended_by_principal_id = :principal_id,
                                   revision = revision + 1, updated_at = clock_timestamp()
                             WHERE organization_id = :organization_id AND id = :activity_id
                             RETURNING id, resource_id, location_id, activity_kind,
                                       started_at, ended_at, revision
                            """
                        ),
                        {
                            "organization_id": command.organization_id,
                            "activity_id": command.resource_activity_id,
                            "ended_at": db_now,
                            "principal_id": command.principal_id,
                        },
                    )
                )
                .mappings()
                .one()
            )
            result = _activity_from_row(updated)
            await _record(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                idempotency_id=idem,
                command_name="resource_activity.end",
                aggregate_kind="ResourceActivity",
                aggregate_id=result.id,
                event_type="resource_activity.ended.v1",
                payload=_activity_to_json(result),
            )
            await complete_idempotency(session, idem, {"activity": _activity_to_json(result)})
            return result


async def _probe_queue_entry(session: AsyncSession, organization_id: UUID, entry_id: UUID) -> RowMapping:
    row = (
        (
            await session.execute(
                text(
                    "SELECT id, service_queue_id FROM request_engine.queue_entries "
                    "WHERE organization_id = :organization_id AND id = :entry_id"
                ),
                {"organization_id": organization_id, "entry_id": entry_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise QueueEntryNotCallable(entry_id, "missing")
    return row


async def _lock_queue(session: AsyncSession, organization_id: UUID, queue_id: UUID) -> None:
    row = (
        await session.execute(
            text(
                "SELECT id FROM request_engine.service_queues "
                "WHERE organization_id = :organization_id AND id = :queue_id AND active FOR UPDATE"
            ),
            {"organization_id": organization_id, "queue_id": queue_id},
        )
    ).first()
    if row is None:
        raise QueueEntryNotCallable(queue_id, "queue_missing_or_inactive")


async def _lock_queue_entry(
    session: AsyncSession, organization_id: UUID, entry_id: UUID
) -> RowMapping:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT id, service_queue_id, subject_party_id, status, revision
                      FROM request_engine.queue_entries
                     WHERE organization_id = :organization_id AND id = :entry_id
                     FOR UPDATE
                    """
                ),
                {"organization_id": organization_id, "entry_id": entry_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise QueueEntryNotCallable(entry_id, "missing")
    return row


async def _lock_resource(session: AsyncSession, organization_id: UUID, resource_id: UUID) -> None:
    row = (
        await session.execute(
            text(
                "SELECT active FROM request_engine.resources "
                "WHERE organization_id = :organization_id AND id = :resource_id FOR UPDATE"
            ),
            {"organization_id": organization_id, "resource_id": resource_id},
        )
    ).first()
    if row is None or row[0] is not True:
        raise ResourceExecutionUnavailable(resource_id, "missing_or_inactive")


async def _lock_session_context(
    session: AsyncSession, organization_id: UUID, session_id: UUID
) -> tuple[RowMapping, RowMapping]:
    probe = (
        (
            await session.execute(
                text(
                    """
                    SELECT s.queue_entry_id, s.resource_id, e.service_queue_id
                      FROM request_engine.service_sessions s
                      JOIN request_engine.queue_entries e
                        ON e.organization_id = s.organization_id AND e.id = s.queue_entry_id
                     WHERE s.organization_id = :organization_id AND s.id = :session_id
                    """
                ),
                {"organization_id": organization_id, "session_id": session_id},
            )
        )
        .mappings()
        .first()
    )
    if probe is None:
        raise ServiceSessionNotFound(session_id)
    await _lock_queue(session, organization_id, cast(UUID, probe["service_queue_id"]))
    entry = await _lock_queue_entry(session, organization_id, cast(UUID, probe["queue_entry_id"]))
    await _lock_resource(session, organization_id, cast(UUID, probe["resource_id"]))
    locked = (
        (
            await session.execute(
                text(
                    """
                    SELECT id, queue_entry_id, resource_id, location_id,
                           actual_workload_classification_id, status,
                           started_at, completed_at, revision
                      FROM request_engine.service_sessions
                     WHERE organization_id = :organization_id AND id = :session_id
                     FOR UPDATE
                    """
                ),
                {"organization_id": organization_id, "session_id": session_id},
            )
        )
        .mappings()
        .one()
    )
    return entry, locked


async def _require_execution_assignment(
    session: AsyncSession,
    *,
    organization_id: UUID,
    resource_id: UUID,
    location_id: UUID,
    at: datetime,
) -> None:
    row = (
        await session.execute(
            text(
                """
                SELECT 1 FROM request_engine.resource_location_assignments
                 WHERE organization_id = :organization_id
                   AND resource_id = :resource_id AND location_id = :location_id
                   AND status = 'active' AND effective_during @> :at
                 LIMIT 1
                """
            ),
            {
                "organization_id": organization_id,
                "resource_id": resource_id,
                "location_id": location_id,
                "at": at,
            },
        )
    ).first()
    if row is None:
        raise ResourceExecutionUnavailable(resource_id, "no_active_location_assignment")


async def _require_workload(
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
        raise ValueError("actual workload classification is missing or inactive")


async def _db_now(session: AsyncSession) -> datetime:
    return cast(datetime, (await session.execute(text("SELECT clock_timestamp()"))).scalar_one())


def _require_revision(row: RowMapping, aggregate_id: UUID, expected: int) -> None:
    actual = cast(int, row["revision"])
    if actual != expected:
        raise LiveServiceRevisionConflict(aggregate_id, expected, actual)


async def _record(
    session: AsyncSession,
    *,
    organization_id: UUID,
    principal_id: UUID,
    idempotency_id: UUID,
    command_name: str,
    aggregate_kind: str,
    aggregate_id: UUID,
    event_type: str,
    payload: dict[str, object],
) -> None:
    await append_audit(
        session,
        organization_id=organization_id,
        principal_id=principal_id,
        command_name=command_name,
        aggregate_kind=aggregate_kind,
        aggregate_id=aggregate_id,
        idempotency_id=idempotency_id,
        details=payload,
    )
    await append_outbox(
        session,
        organization_id=organization_id,
        event_type=event_type,
        aggregate_kind=aggregate_kind,
        aggregate_id=aggregate_id,
        payload=payload,
    )


def _session_from_row(row: RowMapping) -> ServiceSession:
    return ServiceSession(
        id=cast(UUID, row["id"]),
        queue_entry_id=cast(UUID, row["queue_entry_id"]),
        resource_id=cast(UUID, row["resource_id"]),
        location_id=cast(UUID, row["location_id"]),
        status=ServiceSessionStatus(cast(str, row["status"])),
        started_at=cast(datetime, row["started_at"]),
        completed_at=cast(datetime | None, row["completed_at"]),
        actual_workload_classification_id=cast(UUID | None, row["actual_workload_classification_id"]),
        revision=cast(int, row["revision"]),
    )


def _session_to_json(item: ServiceSession) -> dict[str, object]:
    return {
        "id": str(item.id), "queue_entry_id": str(item.queue_entry_id),
        "resource_id": str(item.resource_id), "location_id": str(item.location_id),
        "status": item.status.value, "started_at": item.started_at.isoformat(),
        "completed_at": item.completed_at.isoformat() if item.completed_at else None,
        "actual_workload_classification_id": (
            str(item.actual_workload_classification_id)
            if item.actual_workload_classification_id else None
        ),
        "revision": item.revision,
    }


def _session_from_json(data: dict[str, object]) -> ServiceSession:
    return ServiceSession(
        id=UUID(cast(str, data["id"])),
        queue_entry_id=UUID(cast(str, data["queue_entry_id"])),
        resource_id=UUID(cast(str, data["resource_id"])),
        location_id=UUID(cast(str, data["location_id"])),
        status=ServiceSessionStatus(cast(str, data["status"])),
        started_at=datetime.fromisoformat(cast(str, data["started_at"])),
        completed_at=(
            datetime.fromisoformat(cast(str, data["completed_at"])) if data["completed_at"] else None
        ),
        actual_workload_classification_id=(
            UUID(cast(str, data["actual_workload_classification_id"]))
            if data["actual_workload_classification_id"] else None
        ),
        revision=cast(int, data["revision"]),
    )


def _activity_from_row(row: RowMapping) -> ResourceActivity:
    return ResourceActivity(
        id=cast(UUID, row["id"]), resource_id=cast(UUID, row["resource_id"]),
        location_id=cast(UUID | None, row["location_id"]),
        kind=ResourceActivityKind(cast(str, row["activity_kind"])),
        started_at=cast(datetime, row["started_at"]),
        ended_at=cast(datetime | None, row["ended_at"]), revision=cast(int, row["revision"]),
    )


def _activity_to_json(item: ResourceActivity) -> dict[str, object]:
    return {
        "id": str(item.id), "resource_id": str(item.resource_id),
        "location_id": str(item.location_id) if item.location_id else None,
        "kind": item.kind.value, "started_at": item.started_at.isoformat(),
        "ended_at": item.ended_at.isoformat() if item.ended_at else None,
        "revision": item.revision,
    }


def _activity_from_json(data: dict[str, object]) -> ResourceActivity:
    return ResourceActivity(
        id=UUID(cast(str, data["id"])), resource_id=UUID(cast(str, data["resource_id"])),
        location_id=UUID(cast(str, data["location_id"])) if data["location_id"] else None,
        kind=ResourceActivityKind(cast(str, data["kind"])),
        started_at=datetime.fromisoformat(cast(str, data["started_at"])),
        ended_at=datetime.fromisoformat(cast(str, data["ended_at"])) if data["ended_at"] else None,
        revision=cast(int, data["revision"]),
    )
