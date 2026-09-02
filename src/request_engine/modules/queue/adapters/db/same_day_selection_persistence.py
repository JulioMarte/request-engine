from typing import Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession


async def call_waiting_entry(
    session: AsyncSession,
    organization_id: UUID,
    queue_entry_id: UUID,
) -> RowMapping:
    return (
        (
            await session.execute(
                text(
                    """
                    UPDATE request_engine.queue_entries
                    SET status = 'called',
                        called_at = clock_timestamp(),
                        revision = revision + 1
                    WHERE organization_id = :organization_id
                      AND id = :queue_entry_id
                      AND status = 'waiting'
                    RETURNING id, service_queue_id, subject_party_id, status,
                              admitted_at, called_at, revision
                    """
                ),
                {"organization_id": organization_id, "queue_entry_id": queue_entry_id},
            )
        )
        .mappings()
        .one()
    )


async def insert_selection_fact(
    session: AsyncSession,
    *,
    organization_id: UUID,
    queue_id: UUID,
    queue_entry_id: UUID,
    selection_kind: str,
    reason: str,
    principal_id: UUID,
    called_queue_entry_id: UUID | None = None,
) -> UUID:
    row = (
        await session.execute(
            text(
                """
                INSERT INTO request_engine.queue_selection_facts (
                    organization_id, service_queue_id, queue_entry_id,
                    selection_kind, reason, selected_by_principal_id,
                    called_queue_entry_id
                ) VALUES (
                    :organization_id, :queue_id, :queue_entry_id,
                    :selection_kind, :reason, :principal_id,
                    :called_queue_entry_id
                )
                RETURNING id
                """
            ),
            {
                "organization_id": organization_id,
                "queue_id": queue_id,
                "queue_entry_id": queue_entry_id,
                "selection_kind": selection_kind,
                "reason": reason,
                "principal_id": principal_id,
                "called_queue_entry_id": called_queue_entry_id,
            },
        )
    ).one()
    return row[0]


async def close_current_hold(
    session: AsyncSession,
    *,
    organization_id: UUID,
    queue_entry_id: UUID,
    principal_id: UUID,
    release_reason: Literal["replaced"],
) -> RowMapping | None:
    return (
        (
            await session.execute(
                text(
                    """
                    UPDATE request_engine.queue_recall_holds
                    SET released_at = clock_timestamp(),
                        released_by_principal_id = :principal_id,
                        release_reason = :release_reason
                    WHERE organization_id = :organization_id
                      AND queue_entry_id = :queue_entry_id
                      AND released_at IS NULL
                    RETURNING id, service_queue_id, queue_entry_id, hold_kind,
                              release_at, reason, created_at, released_at
                    """
                ),
                {
                    "organization_id": organization_id,
                    "queue_entry_id": queue_entry_id,
                    "principal_id": principal_id,
                    "release_reason": release_reason,
                },
            )
        )
        .mappings()
        .first()
    )
