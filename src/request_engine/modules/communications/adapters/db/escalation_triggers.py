"""Trigger wiring that replaces bare delivery failure with the escalation step.

``delivery_store`` calls these hooks at its two deadline gates and the fenced
non-retryable finalize branch (after the durable task-failure marking) and at
the per-channel dispatch-resolution failure (instead of raising). Each hook
runs inside the caller's tenant transaction: the failed marking, the
``communication.task_failed.v1`` fact and the escalation step commit or roll
back together, so a trigger fires at most once per failed task. The close is
a CAS on a not-yet-terminal row: a repeated trigger on a task that already
closed re-runs the escalation step but appends no duplicate fact and does not
bump the revision again.
"""

from collections.abc import Collection
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.communications.adapters.db.dispatch_resolution import (
    resolve_dispatch_route_and_contact_point,
)
from request_engine.modules.communications.adapters.db.escalation_commands import (
    escalate_channel,
)
from request_engine.modules.communications.domain.delivery_policy import (
    DeliveryPolicy,
    DeliveryRoute,
)
from request_engine.modules.communications.domain.errors import (
    RecipientChannelUnavailable,
)
from request_engine.modules.communications.domain.escalation_policy import (
    validate_escalation_trigger,
)
from request_engine.platform.outbox.postgres import append_outbox


async def close_task_failed_and_escalate(
    session: AsyncSession,
    *,
    organization_id: UUID,
    communication_task_id: UUID,
    payload: dict[str, object],
    trigger: str,
) -> None:
    """Mark the task failed, append its task_failed fact, then run the step.

    ``payload`` is the exact ``communication.task_failed.v1`` payload the
    caller previously appended inline; the payload ``reason`` doubles as the
    ledger ``failure_class``. The close is a CAS on a not-yet-terminal row:
    when the task already closed, the fact and revision bump are skipped and
    only the (no-op safe) escalation step runs.
    """

    transitioned = (
        await session.execute(
            text(
                """
                UPDATE request_engine.communication_tasks
                SET status = 'failed',
                    revision = revision + 1,
                    updated_at = clock_timestamp()
                WHERE organization_id = :organization_id
                  AND id = :communication_task_id
                  AND status NOT IN ('failed', 'completed', 'cancelled')
                RETURNING id
                """
            ),
            {"organization_id": organization_id, "communication_task_id": communication_task_id},
        )
    ).first() is not None
    if transitioned:
        await append_outbox(
            session,
            organization_id=organization_id,
            event_type="communication.task_failed.v1",
            aggregate_kind="CommunicationTask",
            aggregate_id=communication_task_id,
            payload=payload,
        )
    await escalate_channel(
        session,
        organization_id=organization_id,
        parent_task_id=communication_task_id,
        trigger=validate_escalation_trigger(trigger),
        failure_class=cast(str, payload["reason"]),
    )


async def resolve_route_or_escalate_unreachable(
    session: AsyncSession,
    *,
    organization_id: UUID,
    task: RowMapping,
    policy: DeliveryPolicy,
    configured_provider_keys: Collection[str],
) -> tuple[DeliveryRoute, str, RowMapping] | None:
    """Resolve dispatch, or close the lineage when the pinned channel is dead.

    ``RecipientChannelUnavailable`` means the task's channel has no usable
    contact point (docs/v3/36 section 4 ``recipient_unreachable``): the task
    closes terminally and the escalation step walks the remaining channels.
    Any other configuration error propagates unchanged, keeping the durable
    ``delivery_configuration_invalid`` poison semantics for recipients that no
    policy channel can reach at all.
    """

    try:
        return await resolve_dispatch_route_and_contact_point(
            session,
            organization_id=organization_id,
            task=task,
            policy=policy,
            configured_provider_keys=configured_provider_keys,
        )
    except RecipientChannelUnavailable:
        await close_task_failed_and_escalate(
            session,
            organization_id=organization_id,
            communication_task_id=cast(UUID, task["id"]),
            payload={
                "communication_task_id": str(task["id"]),
                "reason": "recipient_channel_unreachable",
            },
            trigger="recipient_unreachable",
        )
        return None
