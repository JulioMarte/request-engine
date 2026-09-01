"""Child-task write half of the escalation step (docs/v3/36 section 4).

Child task, initial ``dispatch_task`` ScheduledAction, append-only ledger row
and the ``communication.task_escalated.v1`` outbox fact are written in the
caller's single tenant transaction; the deterministic child dedupe key
replays as a no-op and the live-lineage unique index backstops sequentiality.
"""

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.communications.adapters.db.dispatch_actions import (
    DISPATCH_ACTION_TYPE,
    DISPATCH_ACTION_VERSION,
)
from request_engine.modules.communications.adapters.db.escalation_ladder import (
    escalation_dedupe_key,
)
from request_engine.platform.outbox.postgres import append_outbox
from request_engine.platform.scheduling.store import schedule_action


async def create_escalation_child(
    session: AsyncSession,
    *,
    organization_id: UUID,
    parent: RowMapping,
    lineage_id: UUID,
    to_channel: str,
    contact_point: RowMapping,
    ordinal: int,
    expires_at: datetime,
    trigger: str,
    from_channel: str | None,
    failure_class: str,
    db_now: datetime,
) -> UUID | None:
    parent_task_id = cast(UUID, parent["id"])
    child_id = (
        await session.execute(
            text(
                """
                INSERT INTO request_engine.communication_tasks (
                    organization_id, recipient_party_id, contact_point_id, purpose,
                    source_kind, source_id, channel_policy, template_key,
                    template_version, render_context, dedupe_key, not_before,
                    expires_at, status, parent_task_id, lineage_id, escalation_ordinal
                )
                SELECT organization_id, recipient_party_id, :contact_point_id, purpose,
                       source_kind, source_id, channel_policy, template_key,
                       template_version, render_context, :dedupe_key, NULL,
                       :expires_at, 'pending', :parent_task_id, :lineage_id, :ordinal
                  FROM request_engine.communication_tasks
                 WHERE organization_id = :organization_id AND id = :parent_task_id
                ON CONFLICT (organization_id, dedupe_key) WHERE dedupe_key IS NOT NULL
                DO NOTHING
                RETURNING id
                """
            ),
            {
                "organization_id": organization_id,
                "contact_point_id": contact_point["id"],
                "dedupe_key": escalation_dedupe_key(parent_task_id, to_channel, ordinal),
                "expires_at": expires_at,
                "parent_task_id": parent_task_id,
                "lineage_id": lineage_id,
                "ordinal": ordinal,
            },
        )
    ).scalar_one_or_none()
    if child_id is None:
        return None

    await schedule_action(
        session,
        organization_id=organization_id,
        owner_module="communications",
        action_type=DISPATCH_ACTION_TYPE,
        action_version=DISPATCH_ACTION_VERSION,
        subject_kind="CommunicationTask",
        subject_id=child_id,
        dedupe_key=f"communications:dispatch:{child_id}:v1",
        execute_at=db_now,
        payload={"communication_task_id": str(child_id)},
        max_attempts=8,
    )
    await session.execute(
        text(
            "INSERT INTO request_engine.communication_escalations (organization_id,"
            " parent_task_id, child_task_id, trigger, from_channel, to_channel,"
            " ordinal, failure_class) VALUES (:organization_id, :parent_task_id,"
            " :child_task_id, :trigger, :from_channel, :to_channel, :ordinal,"
            " :failure_class)"
        ),
        {
            "organization_id": organization_id,
            "parent_task_id": parent_task_id,
            "child_task_id": child_id,
            "trigger": trigger,
            "from_channel": from_channel,
            "to_channel": to_channel,
            "ordinal": ordinal,
            "failure_class": failure_class,
        },
    )
    await append_outbox(
        session,
        organization_id=organization_id,
        event_type="communication.task_escalated.v1",
        aggregate_kind="CommunicationTask",
        aggregate_id=parent_task_id,
        payload={
            "parent_task_id": str(parent_task_id),
            "child_task_id": str(child_id),
            "trigger": trigger,
            "from_channel": from_channel,
            "to_channel": to_channel,
            "ordinal": ordinal,
        },
    )
    return cast(UUID, child_id)
