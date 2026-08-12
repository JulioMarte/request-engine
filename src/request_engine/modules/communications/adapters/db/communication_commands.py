from datetime import UTC, datetime
from typing import cast

from sqlalchemy import text

from request_engine.modules.communications.adapters.db.task_store import (
    CommunicationTaskIntent,
    communication_task_from_json,
    communication_task_to_json,
    insert_or_reuse_communication_task,
    validate_recipient_and_contact_point,
)
from request_engine.modules.communications.application.commands.create_communication_task import (
    CreateCommunicationTaskCommand,
)
from request_engine.modules.communications.application.errors import InvalidCommunicationWindow
from request_engine.modules.communications.contracts.tasks import CommunicationTask
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
            validate_communication_window(
                not_before=not_before,
                expires_at=expires_at,
                db_now=db_now,
            )
            await validate_recipient_and_contact_point(
                session,
                organization_id=command.organization_id,
                recipient_party_id=command.recipient_party_id,
                contact_point_id=command.contact_point_id,
            )

            task, created = await insert_or_reuse_communication_task(
                session,
                CommunicationTaskIntent(
                    organization_id=command.organization_id,
                    recipient_party_id=command.recipient_party_id,
                    contact_point_id=command.contact_point_id,
                    purpose=command.purpose,
                    source_kind=command.source_kind,
                    source_id=command.source_id,
                    channel_policy=command.channel_policy,
                    template_key=command.template_key,
                    template_version=command.template_version,
                    render_context=command.render_context,
                    dedupe_key=command.dedupe_key,
                    not_before=not_before,
                    expires_at=expires_at,
                ),
            )
            if created:
                await schedule_action(
                    session,
                    organization_id=command.organization_id,
                    owner_module="communications",
                    action_type="dispatch_task",
                    action_version=1,
                    subject_kind="CommunicationTask",
                    subject_id=task.id,
                    dedupe_key=f"communications:dispatch:{task.id}:v1",
                    execute_at=task.not_before or db_now,
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


def validate_communication_window(
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
