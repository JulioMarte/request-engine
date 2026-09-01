"""The escalation step (docs/v3/36 section 4): sequential channel fallback.

``escalate_channel`` runs inside the caller's tenant transaction, after the
triggering failure has marked the parent task failed. Replay/concurrency
discipline: the parent row lock serializes decisions for the same parent; a
live lineage task or an existing ledger row for the parent makes a repeated
trigger a no-op; the ledger UNIQUE ``(organization, parent, to_channel,
ordinal)`` plus the deterministic child dedupe key realize the idempotency
identity ``(parent task, trigger, from_channel, to_channel, ordinal)`` as
durable state; a replayed terminal close is detected from its outbox fact.

Terminal lineage facts (``communication.lineage_unreachable.v1``): reason
``unreachable`` when no usable next channel remains, ``escalation_exhausted``
when the ordinal guard is exhausted, ``fatigue_limited`` when the daily
contact fatigue guard refuses — the first two close the same unreachable
terminal family (docs/v3/40 T4)."""

from typing import cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.communications.adapters.db.escalation_child import (
    create_escalation_child,
)
from request_engine.modules.communications.adapters.db.escalation_ladder import (
    EscalationOutcome,
    parent_trigger_channel,
)
from request_engine.modules.communications.adapters.db.escalation_lineage import (
    revalidated_escalation_parent,
)
from request_engine.modules.communications.adapters.db.escalation_next_channel import (
    child_expires_at,
    database_now,
    resolve_next_channel_contact_point,
    today_contact_count,
)
from request_engine.modules.communications.adapters.db.escalation_terminal import (
    close_lineage_terminal,
)
from request_engine.modules.communications.domain.delivery_policy import parse_delivery_policy
from request_engine.modules.communications.domain.escalation_policy import (
    fatigue_limited,
    parse_escalation_guards,
    validate_escalation_trigger,
)


async def escalate_channel(
    session: AsyncSession,
    *,
    organization_id: UUID,
    parent_task_id: UUID,
    trigger: str,
    failure_class: str,
) -> EscalationOutcome:
    validate_escalation_trigger(trigger)
    revalidated = await revalidated_escalation_parent(
        session,
        organization_id=organization_id,
        parent_task_id=parent_task_id,
    )
    if isinstance(revalidated, str):
        return EscalationOutcome("no_op", None, revalidated)
    parent, prior = revalidated

    from_channel, was_attempted = await parent_trigger_channel(
        session,
        organization_id=organization_id,
        parent_task_id=parent_task_id,
    )

    async def close(reason: str) -> EscalationOutcome:
        return await close_lineage_terminal(
            session,
            organization_id=organization_id,
            lineage_id=cast(UUID, parent["lineage_id"]) or cast(UUID, parent["id"]),
            parent_task_id=parent_task_id,
            trigger=trigger,
            from_channel=from_channel,
            reason=reason,
        )

    channel_policy = cast(dict[str, object], parent["channel_policy"])
    guards = parse_escalation_guards(channel_policy)
    if len(prior) >= guards.max_escalations_per_task:
        return await close("escalation_exhausted")

    contacts = await today_contact_count(
        session,
        organization_id=organization_id,
        recipient_party_id=cast(UUID, parent["recipient_party_id"]),
    )
    if fatigue_limited(contacts, guards):
        return await close("fatigue_limited")

    policy = parse_delivery_policy(channel_policy)
    attempted = {cast(str, row["to_channel"]) for row in prior}
    if was_attempted and from_channel is not None:
        attempted.add(from_channel)
    next_attempt = await resolve_next_channel_contact_point(
        session,
        organization_id=organization_id,
        recipient_party_id=cast(UUID, parent["recipient_party_id"]),
        policy=policy,
        attempted_channels=attempted,
        after_channel=from_channel if was_attempted else None,
    )
    if next_attempt is None:
        return await close("unreachable")

    to_channel, contact_point = next_attempt
    db_now = await database_now(session)
    child_id = await create_escalation_child(
        session,
        organization_id=organization_id,
        parent=parent,
        lineage_id=cast(UUID, parent["lineage_id"]) or cast(UUID, parent["id"]),
        to_channel=to_channel,
        contact_point=contact_point,
        ordinal=len(prior) + 1,
        expires_at=child_expires_at(parent, policy, db_now),
        trigger=trigger,
        from_channel=from_channel,
        failure_class=failure_class,
        db_now=db_now,
    )
    if child_id is None:
        return EscalationOutcome("replayed", None, None)
    return EscalationOutcome("escalated", child_id, None)
