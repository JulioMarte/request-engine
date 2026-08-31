from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.platform.scheduling.store import schedule_action

RECONCILE_ACTION_TYPE = "reconcile_delivery"
RECONCILE_ACTION_VERSION = 1


async def ensure_reconciliation(
    session: AsyncSession,
    *,
    organization_id: UUID,
    delivery_id: UUID,
    db_now: datetime,
    delay_seconds: int,
) -> None:
    existing = cast(
        bool,
        (
            await session.execute(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM request_engine.scheduled_actions
                        WHERE organization_id = :organization_id
                          AND owner_module = 'communications'
                          AND action_type = :action_type
                          AND action_version = :action_version
                          AND subject_kind = 'CommunicationDelivery'
                          AND subject_id = :delivery_id
                          AND CASE
                              WHEN pg_catalog.pg_input_is_valid(payload ->> 'delivery_id', 'uuid')
                              THEN (payload ->> 'delivery_id')::uuid = :delivery_id
                              ELSE false
                          END
                          AND status IN ('pending', 'leased')
                          AND attempt_count < max_attempts
                          AND execute_at > :db_now
                    )
                    """
                ),
                {
                    "organization_id": organization_id,
                    "action_type": RECONCILE_ACTION_TYPE,
                    "action_version": RECONCILE_ACTION_VERSION,
                    "delivery_id": delivery_id,
                    "db_now": db_now,
                },
            )
        ).scalar_one(),
    )
    if existing:
        return

    execute_at = db_now + timedelta(seconds=delay_seconds)
    await schedule_action(
        session,
        organization_id=organization_id,
        owner_module="communications",
        action_type=RECONCILE_ACTION_TYPE,
        action_version=RECONCILE_ACTION_VERSION,
        subject_kind="CommunicationDelivery",
        subject_id=delivery_id,
        dedupe_key=(f"communications:reconcile:{delivery_id}:{execute_at.isoformat()}:v1"),
        execute_at=execute_at,
        payload={"delivery_id": str(delivery_id)},
        max_attempts=12,
    )
