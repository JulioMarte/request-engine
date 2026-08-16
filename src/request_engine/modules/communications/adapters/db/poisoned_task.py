from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.communications.adapters.db.delivery_store import (
    DISPATCH_ACTION_TYPE,
    DISPATCH_ACTION_VERSION,
    fail_poisoned_communication_task,
)


async def fail_poisoned_communication_task_if_orphaned(
    session: AsyncSession,
    *,
    organization_id: UUID,
    communication_task_id: UUID,
    scheduled_action_id: UUID,
    reason: str,
) -> bool:
    """Fail a task only when poison work is its last executable dispatch intent.

    Locking the task first serializes this decision with normal delivery state
    transitions and retry scheduling, both of which also lock the task before
    mutating it. Initial dispatch creation occurs in the same transaction as
    task creation, so it is not visible independently. A malformed duplicate
    action may therefore be dead-lettered without incorrectly terminalizing a
    task that still has valid work.
    """

    task_status = (
        await session.execute(
            text(
                """
                SELECT status
                FROM request_engine.communication_tasks
                WHERE organization_id = :organization_id
                  AND id = :communication_task_id
                FOR UPDATE
                """
            ),
            {
                "organization_id": organization_id,
                "communication_task_id": communication_task_id,
            },
        )
    ).scalar_one_or_none()
    if task_status is None or task_status in {"completed", "cancelled", "failed"}:
        return False

    sibling_dispatch_exists = bool(
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
                          AND subject_kind = 'CommunicationTask'
                          AND subject_id = :communication_task_id
                          AND CASE
                              WHEN pg_catalog.pg_input_is_valid(
                                  payload ->> 'communication_task_id',
                                  'uuid'
                              )
                              THEN (payload ->> 'communication_task_id')::uuid
                                   = :communication_task_id
                              ELSE false
                          END
                          AND id <> :scheduled_action_id
                          AND status IN ('pending', 'leased')
                          AND attempt_count < max_attempts
                    )
                    """
                ),
                {
                    "organization_id": organization_id,
                    "action_type": DISPATCH_ACTION_TYPE,
                    "action_version": DISPATCH_ACTION_VERSION,
                    "communication_task_id": communication_task_id,
                    "scheduled_action_id": scheduled_action_id,
                },
            )
        ).scalar_one()
    )
    if sibling_dispatch_exists:
        return False

    return await fail_poisoned_communication_task(
        session,
        organization_id=organization_id,
        communication_task_id=communication_task_id,
        scheduled_action_id=scheduled_action_id,
        reason=reason,
    )
