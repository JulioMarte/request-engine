"""Escalation ladder reads (docs/v3/36 section 4 sequential fallback).

One escalation decision has the deterministic identity
``(parent task, trigger, from_channel, to_channel, ordinal)``: the ledger
UNIQUE ``(organization, parent, to_channel, ordinal)`` plus the child dedupe
key realize it as durable state; the attempted channel set and lineage count
derive the sequential ladder position from the same ledger.
"""

from dataclasses import dataclass
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class EscalationOutcome:
    """``escalate_channel`` result: escalated / replayed / terminal / no_op."""

    state: str
    child_task_id: UUID | None
    reason: str | None


def escalation_dedupe_key(parent_task_id: UUID, to_channel: str, ordinal: int) -> str:
    return f"communication:escalation:{parent_task_id}:{to_channel}:{ordinal}:v1"


async def parent_trigger_channel(
    session: AsyncSession,
    *,
    organization_id: UUID,
    parent_task_id: UUID,
) -> tuple[str | None, bool]:
    """Channel whose failure triggered the escalation, and whether it ran.

    Returns ``(channel, attempted)``: the parent's latest delivery channel
    when the parent attempted one, otherwise the pinned contact point's
    channel (deadline missed before dispatch), else ``(None, False)``. Only a
    real delivery attempt makes ``attempted`` True, which the ladder walk
    must step past.
    """

    channel = await parent_attempted_channel(
        session,
        organization_id=organization_id,
        parent_task_id=parent_task_id,
    )
    if channel is not None:
        return channel, True
    return await parent_pinned_channel(
        session,
        organization_id=organization_id,
        parent_task_id=parent_task_id,
    ), False


async def parent_attempted_channel(
    session: AsyncSession,
    *,
    organization_id: UUID,
    parent_task_id: UUID,
) -> str | None:
    """Channel of the parent's latest delivery attempt, when one exists."""

    return cast(
        str | None,
        (
            await session.execute(
                text(
                    "SELECT channel FROM request_engine.communication_deliveries"
                    " WHERE organization_id = :organization_id"
                    " AND communication_task_id = :parent_task_id"
                    " ORDER BY attempt_no DESC LIMIT 1"
                ),
                {"organization_id": organization_id, "parent_task_id": parent_task_id},
            )
        ).scalar_one_or_none(),
    )


async def parent_pinned_channel(
    session: AsyncSession,
    *,
    organization_id: UUID,
    parent_task_id: UUID,
) -> str | None:
    """Endpoint channel of the parent's pinned contact point, when pinned."""

    return cast(
        str | None,
        (
            await session.execute(
                text(
                    "SELECT p.channel FROM request_engine.communication_tasks t"
                    " JOIN request_engine.party_contact_points p"
                    " ON p.organization_id = t.organization_id AND p.id = t.contact_point_id"
                    " WHERE t.organization_id = :organization_id"
                    " AND t.id = :parent_task_id"
                ),
                {"organization_id": organization_id, "parent_task_id": parent_task_id},
            )
        ).scalar_one_or_none(),
    )


async def live_lineage_task_exists(
    session: AsyncSession,
    *,
    organization_id: UUID,
    lineage_id: UUID,
) -> bool:
    """True while any pending/delivering task of the lineage is still live."""

    return cast(
        bool,
        (
            await session.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM request_engine.communication_tasks"
                    " WHERE organization_id = :organization_id"
                    " AND lineage_id = :lineage_id"
                    " AND status IN ('pending', 'delivering'))"
                ),
                {"organization_id": organization_id, "lineage_id": lineage_id},
            )
        ).scalar_one(),
    )
