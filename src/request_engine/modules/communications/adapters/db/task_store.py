import json
from dataclasses import dataclass
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.communications.application.errors import (
    CommunicationDedupeConflict,
    ContactPointNotUsable,
    RecipientNotFound,
)
from request_engine.modules.communications.contracts.tasks import (
    CommunicationTask,
    CommunicationTaskStatus,
)


@dataclass(frozen=True, slots=True)
class CommunicationTaskIntent:
    organization_id: UUID
    recipient_party_id: UUID
    contact_point_id: UUID | None
    purpose: str
    source_kind: str | None
    source_id: UUID | None
    channel_policy: dict[str, object]
    template_key: str
    template_version: int
    render_context: dict[str, object]
    dedupe_key: str | None
    not_before: datetime | None
    expires_at: datetime | None


async def validate_recipient_and_contact_point(
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


async def insert_or_reuse_communication_task(
    session: AsyncSession,
    intent: CommunicationTaskIntent,
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
                    "organization_id": intent.organization_id,
                    "recipient_party_id": intent.recipient_party_id,
                    "contact_point_id": intent.contact_point_id,
                    "purpose": intent.purpose,
                    "source_kind": intent.source_kind,
                    "source_id": intent.source_id,
                    "channel_policy": _json(intent.channel_policy),
                    "template_key": intent.template_key,
                    "template_version": intent.template_version,
                    "render_context": _json(intent.render_context),
                    "dedupe_key": intent.dedupe_key,
                    "not_before": intent.not_before,
                    "expires_at": intent.expires_at,
                },
            )
        )
        .mappings()
        .first()
    )
    if row is not None:
        return communication_task_from_row(row), True

    if intent.dedupe_key is None:
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
                    "organization_id": intent.organization_id,
                    "dedupe_key": intent.dedupe_key,
                },
            )
        )
        .mappings()
        .one()
    )
    task = communication_task_from_row(existing)
    expected = (
        intent.recipient_party_id,
        intent.contact_point_id,
        intent.purpose,
        intent.source_kind,
        intent.source_id,
        intent.channel_policy,
        intent.template_key,
        intent.template_version,
        intent.render_context,
        intent.not_before,
        intent.expires_at,
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
        raise CommunicationDedupeConflict(intent.dedupe_key)
    return task, False


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
    return json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))
