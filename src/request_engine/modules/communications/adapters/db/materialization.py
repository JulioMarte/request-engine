import json
from datetime import UTC, datetime
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.communications.adapters.db.communication_commands import (
    validate_communication_window,
)
from request_engine.modules.communications.adapters.db.task_store import (
    CommunicationTaskIntent,
    insert_or_reuse_communication_task,
    validate_recipient_and_contact_point,
)
from request_engine.modules.communications.contracts.tasks import CommunicationTask
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.outbox.postgres import append_outbox
from request_engine.platform.scheduling.store import schedule_action


@dataclass(frozen=True, slots=True)
class InternalCommunicationIntent:
    organization_id: UUID
    recipient_party_id: UUID
    purpose: str
    source_kind: str
    source_id: UUID
    dedupe_key: str
    channel_policy: dict[str, object]
    template_key: str
    template_version: int
    render_context: dict[str, object]
    contact_point_id: UUID | None = None
    not_before: datetime | None = None
    expires_at: datetime | None = None


class PostgresInternalCommunicationMaterializer:
    """Materialize event-derived communication intent without inventing an actor Principal."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def materialize(self, intent: InternalCommunicationIntent) -> CommunicationTask:
        if not intent.dedupe_key or not intent.source_kind:
            raise ValueError("dedupe_key and source_kind are required for internal materialization")
        if not intent.purpose or not intent.template_key or intent.template_version <= 0:
            raise ValueError("purpose, template_key and positive template_version are required")

        not_before = _aware_utc(intent.not_before)
        expires_at = _aware_utc(intent.expires_at)
        async with tenant_transaction(self._session_factory, intent.organization_id) as session:
            db_now = (await session.execute(text("SELECT clock_timestamp()"))).scalar_one()
            validate_communication_window(
                not_before=not_before,
                expires_at=expires_at,
                db_now=db_now,
            )
            await validate_recipient_and_contact_point(
                session,
                organization_id=intent.organization_id,
                recipient_party_id=intent.recipient_party_id,
                contact_point_id=intent.contact_point_id,
            )
            task, created = await insert_or_reuse_communication_task(
                session,
                CommunicationTaskIntent(
                    organization_id=intent.organization_id,
                    recipient_party_id=intent.recipient_party_id,
                    contact_point_id=intent.contact_point_id,
                    purpose=intent.purpose,
                    source_kind=intent.source_kind,
                    source_id=intent.source_id,
                    channel_policy=intent.channel_policy,
                    template_key=intent.template_key,
                    template_version=intent.template_version,
                    render_context=intent.render_context,
                    dedupe_key=intent.dedupe_key,
                    not_before=not_before,
                    expires_at=expires_at,
                ),
            )
            if created:
                await schedule_action(
                    session,
                    organization_id=intent.organization_id,
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
                await append_outbox(
                    session,
                    organization_id=intent.organization_id,
                    event_type="communication.task_created.v1",
                    aggregate_kind="CommunicationTask",
                    aggregate_id=task.id,
                    payload={
                        "communication_task_id": str(task.id),
                        "recipient_party_id": str(task.recipient_party_id),
                        "purpose": task.purpose,
                    },
                )

            await session.execute(
                text(
                    """
                    INSERT INTO request_engine.audit_records (
                        organization_id,
                        actor_principal_id,
                        command_name,
                        aggregate_kind,
                        aggregate_id,
                        correlation_data,
                        details
                    ) VALUES (
                        :organization_id,
                        NULL,
                        'communications.materialize_internal',
                        'CommunicationTask',
                        :task_id,
                        CAST(:correlation_data AS jsonb),
                        CAST(:details AS jsonb)
                    )
                    """
                ),
                {
                    "organization_id": intent.organization_id,
                    "task_id": task.id,
                    "correlation_data": json.dumps(
                        {"source_kind": intent.source_kind, "source_id": str(intent.source_id)},
                        separators=(",", ":"),
                    ),
                    "details": json.dumps(
                        {
                            "purpose": task.purpose,
                            "dedupe_key": task.dedupe_key,
                            "dedupe_reuse": not created,
                            "actor_mode": "system_event",
                        },
                        separators=(",", ":"),
                    ),
                },
            )
            return task


def _aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("communication window timestamps must be timezone-aware")
    return value.astimezone(UTC)
