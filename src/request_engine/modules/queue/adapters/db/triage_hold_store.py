from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.queue.application.commands.triage import RecallHoldCommand
from request_engine.modules.queue.contracts.triage import RecallHold


async def insert_recall_hold(
    session: AsyncSession,
    command: RecallHoldCommand,
) -> RecallHold:
    row = (
        await session.execute(
            text(
                """
                INSERT INTO request_engine.queue_entry_recall_holds (
                    organization_id, queue_entry_id, condition_kind,
                    until_at, event_key, reason, created_by_principal_id
                ) VALUES (
                    :organization_id, :entry_id, :kind,
                    :until_at, :event_key, :reason, :principal_id
                )
                RETURNING id, created_at
                """
            ),
            {
                "organization_id": command.organization_id,
                "entry_id": command.queue_entry_id,
                "kind": command.condition_kind.value,
                "until_at": command.until_at,
                "event_key": command.event_key,
                "reason": command.reason,
                "principal_id": command.principal_id,
            },
        )
    ).one()
    return RecallHold(
        id=cast(UUID, row[0]),
        queue_entry_id=command.queue_entry_id,
        condition_kind=command.condition_kind,
        until_at=command.until_at,
        event_key=command.event_key,
        reason=command.reason,
        created_at=cast(datetime, row[1]),
    )
