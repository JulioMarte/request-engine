import json
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def schedule_action(
    session: AsyncSession,
    *,
    organization_id: UUID,
    owner_module: str,
    action_type: str,
    action_version: int,
    dedupe_key: str,
    execute_at: datetime,
    payload: dict[str, object],
    subject_kind: str | None = None,
    subject_id: UUID | None = None,
    max_attempts: int = 8,
) -> UUID:
    """Append one durable ScheduledAction in the caller's tenant transaction."""

    if not owner_module or not action_type or not dedupe_key:
        raise ValueError("owner_module, action_type and dedupe_key are required")
    if action_version <= 0 or max_attempts <= 0:
        raise ValueError("action_version and max_attempts must be positive")
    return cast(
        UUID,
        (
            await session.execute(
                text(
                    """
                    INSERT INTO request_engine.scheduled_actions (
                        organization_id,
                        owner_module,
                        action_type,
                        action_version,
                        subject_kind,
                        subject_id,
                        payload,
                        dedupe_key,
                        execute_at,
                        next_attempt_at,
                        max_attempts
                    ) VALUES (
                        :organization_id,
                        :owner_module,
                        :action_type,
                        :action_version,
                        :subject_kind,
                        :subject_id,
                        CAST(:payload AS jsonb),
                        :dedupe_key,
                        :execute_at,
                        :execute_at,
                        :max_attempts
                    )
                    ON CONFLICT (organization_id, dedupe_key)
                    DO UPDATE SET dedupe_key = EXCLUDED.dedupe_key
                    RETURNING id
                    """
                ),
                {
                    "organization_id": organization_id,
                    "owner_module": owner_module,
                    "action_type": action_type,
                    "action_version": action_version,
                    "subject_kind": subject_kind,
                    "subject_id": subject_id,
                    "payload": json.dumps(payload, default=str, separators=(",", ":")),
                    "dedupe_key": dedupe_key,
                    "execute_at": execute_at,
                    "max_attempts": max_attempts,
                },
            )
        ).scalar_one(),
    )
