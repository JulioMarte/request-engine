from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.communications.application.commands.create_communication_task import (
    CreateCommunicationTaskCommand,
)
from request_engine.modules.communications.application.errors import (
    CommunicationDedupeConflict,
    ContactPointNotUsable,
    InvalidCommunicationWindow,
    RecipientNotFound,
)
from request_engine.modules.communications.contracts.tasks import (
    CommunicationTask,
    CommunicationTaskStatus,
)
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)
from request_engine.platform.outbox.postgres import append_outbox
from request_engine.platform.scheduling.store import schedule_action


class PostgresCommunicationCommands:
    """Tenant-scoped durable communication intent commands."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def create_communication_task(
        self,
        command: CreateCommunicationTaskCommand,
    ) -> CommunicationTask:
        not_before = _aware_utc(command.not_before, "not_before")
        expires_at = _aware_utc(command.expires_at, "expires_at")
        fingerprint = command_fingerprint(
            "communications.create_task",
            {
                "recipient_party_id": command.recipient_party_id,
                "contact_point_id": command.contact_point_id,
                "purpose": command.purpose,
                "source_kind": command.source_kind,
                "source_id": command.source_id,
                "channel_policy": command.channel_policy,
                "template_key": command.template_key,
                "template_version": command.template_version,
                "render_context": command.render_context,
                "dedupe_key": command.dedupe_key,
                "not_before": not_before,
                "expires_at": expires_at,
            },
        )

        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability="communications.create_task",
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return communication_task_from_json(
                    cast(dict[str, object], replay["communication_task"])
                )

            db_now = cast(
                datetime,
                (await session.execute(text("SELECT clock_timestamp()"))).scalar_one(),
            )
            _validate_window(not_before=not_before, expires_at=expires_at, db_now=db_now)
            await _validate_recipient_and_contact_point(
                session,
                organization_id=command.organization_id,
                recipient_party_id=command.recipient_party_id,
                contact_point_id=command.contact_point_id,
            )

            task, created = await _insert_or_reuse_task(
                session,
                command=command,
                not_before=not_before,
                expires_at=expires_at,
            )
            execute_at = max(db_now, task.not_before or db_now)
            await schedule_action(
                session,
                organization_id=command.organization_id,
                owner_module="communications",
                action_type="dispatch_task",
                action_version=1,
                subject_kind="CommunicationTask",
                subject_id=task.id,
                dedupe_key=f"communications:dispatch:{task.id}:v1",
                execute_at=execute_at,
                payload={"communication_task_id": str(task.id)},
                max_attempts=8,
            )

            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name="communications.create_task",
                aggregate_kind="CommunicationTask",
                aggregate_id=task.id,
                idempotency_id=idempotency_id,
                details={
                    "purpose": task.purpose,
                    "dedupe_key": task.dedupe_key,
                    "dedupe_reuse": not created,
                },
            )
            if created:
                await append_outbox(
                    session,
                    organization_id=command.organization_id,
                    event_type="communication.task_created.v1",
                    aggregate_kind="CommunicationTask",
                    aggregate_id=task.id,
                    payload={
                        "communication_task_id": str(task.id),
                        "recipient_party_id": str(task.recipient_party_id),
                        "purpose": task.purpose,
                        "not_before": (
                            task.not_before.isoformat() if task.not_before is not None else None
                        ),
                        "expires_at": (
                            task.expires_at.isoformat() if task.expires_at is not None else None
                        ),
                    },
                )
            await complete_idempotency(
                session,
                idempotency_id,
                {"communication_task": communication_task_to_json(task)},
            )
            return task


async def _insert_or_reuse_task(
    session: AsyncSession,
    *,
    command: CreateCommunicationTaskCommand,
    not_before: datetime | None,
    expires_at: datetime | None,
) -> tuple[CommunicationTask, bool]:
    row = (
        (
            await session.execute(
                text(
                    """
                    INSERT INTO request_engine.communication_tasks (
                        organization_id,
                        recipient_party_id,
                        contact_point_id,
                        purpose,
                        source_kind,
                        source_id,
                        channel_policy,
                        template_key,
                        template_version,
                        render_context,
                        dedupe_key,
                        not_before,
                        expires_at
                    ) VALUES (
                        :organization_id,
                        :recipient_party_id,
                        :contact_point_id,
                        :purpose,
                        :source_kind,
                        :source_id,
                        CAST(:channel_policy AS jsonb),
                        :template_key,
                        :template_version,
                        CAST(:render_context AS jsonb),
                        :dedupe_key,
                        :not_before,
                        :expires_at
                    )
                    ON CONFLICT (organization_id, dedupe_key)
                    WHERE dedupe_key IS NOT NULL
                    DO NOTHING
                    RETURNING *
                    """
                ),
                {
                    "organization_id": command.organization_id,
                    "recipient_party_id": command.recipient_party_id,
                    "contact_point_id": command.contact_point_id,
                    "purpose": command.purpose,
                    "source_kind": command.source_kind,
                    "source_id": command.source_id,
                    "channel_policy": _json(command.channel_policy),
                    "template_key": command.template_key,
                    "template_version": command.template_version,
                    "render_context": _json(command.render_context),
                    "dedupe_key": command.dedupe_key,
                    "not_before": not_before,
                    "expires_at": expires_at,
                },
            )
        )
        .mappings()
        .first()
    )
    if row is not None:
        return communication_task_from_row(row), True

    if command.dedupe_key is None:
        raise RuntimeError("communication task insert unexpectedly returned no row")

    existing = (
        (
            await session.execute(
                text(
                    """
                    SELECT *
                    FROM request_engine.communication_tasks
                    WHERE organization_id = :organization_id
                      AND dedupe_key = :dedupe_key
                    FOR UPDATE
                    """
                ),
                {
                    "organization_id": command.organization_id,
                    "dedupe_key": command.dedupe_key,
                },
            )
        )
        .mappings()
        .one()
    )
    task = communication_task_from_row(existing)
    expected = (
        command.recipient_party_id,
        command.contact_point_id,
        command.purpose,
        command.source_kind,
        command.source_id,
        command.channel_policy,
        command.template_key,
        command.template_version,
        command.render_context,
        not_before,
        expires_at,
    )
    actual = (
        task.recipient_party_id,
        task.contact_point_id,
        task.purpose,
        task.source_kind,
        task.source_id,
        task.channel_policy,
        task.template_key,
        task.template_version,
        task.render_context,
        task.not_before,
        task.expires_at,
    )
    if actual != expected:
        raise CommunicationDedupeConflict(command.dedupe_key)
    return task, False


async def _validate_recipient_and_contact_point(
    session: AsyncSession,
    *,
    organization_id: UUID,
    recipient_party_id: UUID,
    contact_point_id: UUID | None,
) -> None:
    recipient_exists = (
        await session.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM request_engine.parties
                    WHERE organization_id = :organization_id
                      AND id = :recipient_party_id
                      AND active
                )
                """
            ),
            {
                "organization_id": organization_id,
                "recipient_party_id": recipient_party_id,
            },
        )
    ).scalar_one()
    if recipient_exists is not True:
        raise RecipientNotFound(recipient_party_id)

    if contact_point_id is None:
        return
    contact_exists = (
        await session.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM request_engine.party_contact_points
                    WHERE organization_id = :organization_id
                      AND id = :contact_point_id
                      AND party_id = :recipient_party_id
                      AND active
                )
                """
            ),
            {
                "organization_id": organization_id,
                "contact_point_id": contact_point_id,
                "recipient_party_id": recipient_party_id,
            },
        )
    ).scalar_one()
    if contact_exists is not True:
        raise ContactPointNotUsable(contact_point_id)


def _validate_window(
    *,
    not_before: datetime | None,
    expires_at: datetime | None,
    db_now: datetime,
) -> None:
    if expires_at is not None and expires_at <= db_now:
        raise InvalidCommunicationWindow("expires_at must be after database wall-clock time")
    if not_before is not None and expires_at is not None and expires_at <= not_before:
        raise InvalidCommunicationWindow("expires_at must be after not_before")


def _aware_utc(value: datetime | None, field: str) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def communication_task_from_row(row: RowMapping) -> CommunicationTask:
    return CommunicationTask(
        id=cast(UUID, row["id"]),
        recipient_party_id=cast(UUID, row["recipient_party_id"]),
        contact_point_id=cast(UUID | None, row["contact_point_id"]),
        purpose=cast(str, row["purpose"]),
        source_kind=cast(str | None, row["source_kind"]),
        source_id=cast(UUID | None, row["source_id"]),
        channel_policy=cast(dict[str, object], row["channel_policy"]),
        template_key=cast(str, row["template_key"]),
        template_version=cast(int, row["template_version"]),
        render_context=cast(dict[str, object], row["render_context"]),
        dedupe_key=cast(str | None, row["dedupe_key"]),
        not_before=cast(datetime | None, row["not_before"]),
        expires_at=cast(datetime | None, row["expires_at"]),
        status=CommunicationTaskStatus(cast(str, row["status"])),
        revision=cast(int, row["revision"]),
    )


def communication_task_to_json(task: CommunicationTask) -> dict[str, object]:
    return {
        "id": str(task.id),
        "recipient_party_id": str(task.recipient_party_id),
        "contact_point_id": str(task.contact_point_id) if task.contact_point_id else None,
        "purpose": task.purpose,
        "source_kind": task.source_kind,
        "source_id": str(task.source_id) if task.source_id else None,
        "channel_policy": task.channel_policy,
        "template_key": task.template_key,
        "template_version": task.template_version,
        "render_context": task.render_context,
        "dedupe_key": task.dedupe_key,
        "not_before": task.not_before.isoformat() if task.not_before else None,
        "expires_at": task.expires_at.isoformat() if task.expires_at else None,
        "status": task.status.value,
        "revision": task.revision,
    }


def communication_task_from_json(data: dict[str, object]) -> CommunicationTask:
    contact_raw = cast(str | None, data["contact_point_id"])
    source_raw = cast(str | None, data["source_id"])
    not_before_raw = cast(str | None, data["not_before"])
    expires_raw = cast(str | None, data["expires_at"])
    return CommunicationTask(
        id=UUID(cast(str, data["id"])),
        recipient_party_id=UUID(cast(str, data["recipient_party_id"])),
        contact_point_id=UUID(contact_raw) if contact_raw else None,
        purpose=cast(str, data["purpose"]),
        source_kind=cast(str | None, data["source_kind"]),
        source_id=UUID(source_raw) if source_raw else None,
        channel_policy=cast(dict[str, object], data["channel_policy"]),
        template_key=cast(str, data["template_key"]),
        template_version=cast(int, data["template_version"]),
        render_context=cast(dict[str, object], data["render_context"]),
        dedupe_key=cast(str | None, data["dedupe_key"]),
        not_before=datetime.fromisoformat(not_before_raw) if not_before_raw else None,
        expires_at=datetime.fromisoformat(expires_raw) if expires_raw else None,
        status=CommunicationTaskStatus(cast(str, data["status"])),
        revision=cast(int, data["revision"]),
    )


def _json(value: dict[str, object]) -> str:
    import json

    return json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))
