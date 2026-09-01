"""Escalation lineage re-validation and ledger read (docs/v3/36 section 4).

The parent row lock is the serialization point of the escalation step: a
repeated or concurrent trigger re-validates under the lock and becomes a
no-op when the condition no longer holds (parent not failed, a live lineage
task exists, or the parent already escalated — the ledger row is the replay
record of one escalation decision).
"""

from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.communications.adapters.db.escalation_ladder import (
    live_lineage_task_exists,
)
from request_engine.modules.communications.application.errors import (
    CommunicationTaskNotFound,
)


async def revalidated_escalation_parent(
    session: AsyncSession,
    *,
    organization_id: UUID,
    parent_task_id: UUID,
) -> tuple[RowMapping, list[RowMapping]] | str:
    """Lock the parent and re-validate that the escalation trigger still holds.

    Returns the locked parent row plus the lineage's prior ledger rows, or a
    no-op rejection reason when the condition does not hold.
    """

    parent = (
        (
            await session.execute(
                text(
                    "SELECT * FROM request_engine.communication_tasks"
                    " WHERE organization_id = :organization_id"
                    " AND id = :parent_task_id FOR UPDATE"
                ),
                {"organization_id": organization_id, "parent_task_id": parent_task_id},
            )
        )
        .mappings()
        .first()
    )
    if parent is None:
        raise CommunicationTaskNotFound(parent_task_id)
    status = cast(str, parent["status"])
    if status != "failed":
        return f"parent_{status}"

    lineage_id = cast(UUID | None, parent["lineage_id"]) or cast(UUID, parent["id"])
    if await live_lineage_task_exists(
        session,
        organization_id=organization_id,
        lineage_id=lineage_id,
    ):
        return "live_lineage_task"

    prior = await prior_escalations(
        session,
        organization_id=organization_id,
        lineage_id=lineage_id,
    )
    if any(cast(UUID, row["parent_task_id"]) == parent_task_id for row in prior):
        return "already_escalated"
    return parent, prior


async def prior_escalations(
    session: AsyncSession,
    *,
    organization_id: UUID,
    lineage_id: UUID,
) -> list[RowMapping]:
    """Ledger rows for every escalation already taken inside the lineage."""

    rows = (
        await session.execute(
            text(
                "SELECT e.parent_task_id, e.to_channel, e.ordinal"
                " FROM request_engine.communication_escalations e"
                " WHERE e.organization_id = :organization_id"
                " AND e.parent_task_id IN ("
                "SELECT t.id FROM request_engine.communication_tasks t"
                " WHERE t.organization_id = :organization_id"
                " AND (t.id = :lineage_id OR t.lineage_id = :lineage_id))"
            ),
            {"organization_id": organization_id, "lineage_id": lineage_id},
        )
    ).mappings()
    return list(rows.all())
