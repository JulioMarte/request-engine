import json
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.platform.scheduling.errors import ScheduledActionDedupeConflict


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
    """Append one durable ScheduledAction in the caller's tenant transaction.

    Reusing a dedupe key is allowed only for the exact same scheduled work. A
    different payload/target under the same key is a semantic conflict rather
    than an implicit overwrite. Correlation metadata is durable transport
    provenance and does not participate in semantic dedupe equality.
    """

    if not owner_module or not action_type or not dedupe_key:
        raise ValueError("owner_module, action_type and dedupe_key are required")
    if action_version <= 0 or max_attempts <= 0:
        raise ValueError("action_version and max_attempts must be positive")

    payload_json = json.dumps(payload, default=str, sort_keys=True, separators=(",", ":"))
    inserted = (
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
                    max_attempts,
                    correlation_data
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
                    :max_attempts,
                    jsonb_strip_nulls(jsonb_build_object(
                        'correlation_id', NULLIF(
                            current_setting('request_engine.correlation_id', true), ''
                        )
                    ))
                )
                ON CONFLICT (organization_id, dedupe_key) DO NOTHING
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
                "payload": payload_json,
                "dedupe_key": dedupe_key,
                "execute_at": execute_at,
                "max_attempts": max_attempts,
            },
        )
    ).scalar_one_or_none()
    if inserted is not None:
        return cast(UUID, inserted)

    existing = (
        (
            await session.execute(
                text(
                    """
                    SELECT id, owner_module, action_type, action_version,
                           subject_kind, subject_id, payload,
                           execute_at, max_attempts
                    FROM request_engine.scheduled_actions
                    WHERE organization_id = :organization_id
                      AND dedupe_key = :dedupe_key
                    FOR UPDATE
                    """
                ),
                {
                    "organization_id": organization_id,
                    "dedupe_key": dedupe_key,
                },
            )
        )
        .mappings()
        .one()
    )

    expected = (
        owner_module,
        action_type,
        action_version,
        subject_kind,
        subject_id,
        payload,
        execute_at,
        max_attempts,
    )
    actual = (
        cast(str, existing["owner_module"]),
        cast(str, existing["action_type"]),
        cast(int, existing["action_version"]),
        cast(str | None, existing["subject_kind"]),
        cast(UUID | None, existing["subject_id"]),
        cast(dict[str, object], existing["payload"]),
        cast(datetime, existing["execute_at"]),
        cast(int, existing["max_attempts"]),
    )
    if actual != expected:
        raise ScheduledActionDedupeConflict(dedupe_key)
    return cast(UUID, existing["id"])


async def cancel_action(
    session: AsyncSession,
    *,
    organization_id: UUID,
    action_id: UUID,
) -> str:
    """Cancel pending or leased work and fence any claim token that lost the race."""

    return cast(
        str,
        (
            await session.execute(
                text(
                    """
                    SELECT request_cmd.cancel_scheduled_action(
                        :organization_id,
                        :action_id
                    )
                    """
                ),
                {"organization_id": organization_id, "action_id": action_id},
            )
        ).scalar_one(),
    )
