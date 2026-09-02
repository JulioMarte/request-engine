from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.queue.contracts.same_day_selection import RecallHold, RecallHoldKind


async def database_clock(session: AsyncSession) -> datetime:
    row = (await session.execute(text("SELECT clock_timestamp()"))).one()
    return cast(datetime, row[0])


async def insert_recall_hold(
    session: AsyncSession,
    *,
    organization_id: UUID,
    queue_id: UUID,
    queue_entry_id: UUID,
    queue_entry_revision: int,
    kind: RecallHoldKind,
    release_at: datetime | None,
    reason: str | None,
    principal_id: UUID,
) -> RecallHold:
    row = (
        (
            await session.execute(
                text(
                    """
                    INSERT INTO request_engine.queue_recall_holds (
                        organization_id, service_queue_id, queue_entry_id,
                        hold_kind, release_at, reason, created_by_principal_id
                    ) VALUES (
                        :organization_id, :queue_id, :queue_entry_id,
                        :hold_kind, :release_at, :reason, :principal_id
                    )
                    RETURNING id, service_queue_id, queue_entry_id, hold_kind,
                              release_at, reason, created_at, released_at
                    """
                ),
                {
                    "organization_id": organization_id,
                    "queue_id": queue_id,
                    "queue_entry_id": queue_entry_id,
                    "hold_kind": kind.value,
                    "release_at": release_at,
                    "reason": reason,
                    "principal_id": principal_id,
                },
            )
        )
        .mappings()
        .one()
    )
    return recall_hold_from_row(row, queue_entry_revision)


def recall_hold_from_row(row: RowMapping, queue_entry_revision: int) -> RecallHold:
    return RecallHold(
        id=cast(UUID, row["id"]),
        queue_id=cast(UUID, row["service_queue_id"]),
        queue_entry_id=cast(UUID, row["queue_entry_id"]),
        queue_entry_revision=queue_entry_revision,
        kind=RecallHoldKind(cast(str, row["hold_kind"])),
        release_at=cast(datetime | None, row["release_at"]),
        reason=cast(str | None, row["reason"]),
        created_at=cast(datetime, row["created_at"]),
        released_at=cast(datetime | None, row["released_at"]),
    )


def recall_hold_to_json(item: RecallHold) -> dict[str, object]:
    return {
        "id": str(item.id),
        "queue_id": str(item.queue_id),
        "queue_entry_id": str(item.queue_entry_id),
        "queue_entry_revision": item.queue_entry_revision,
        "kind": item.kind.value,
        "release_at": item.release_at.isoformat() if item.release_at else None,
        "reason": item.reason,
        "created_at": item.created_at.isoformat(),
        "released_at": item.released_at.isoformat() if item.released_at else None,
    }


def recall_hold_from_json(data: dict[str, object]) -> RecallHold:
    release_at = cast(str | None, data["release_at"])
    released_at = cast(str | None, data["released_at"])
    return RecallHold(
        id=UUID(cast(str, data["id"])),
        queue_id=UUID(cast(str, data["queue_id"])),
        queue_entry_id=UUID(cast(str, data["queue_entry_id"])),
        queue_entry_revision=cast(int, data["queue_entry_revision"]),
        kind=RecallHoldKind(cast(str, data["kind"])),
        release_at=datetime.fromisoformat(release_at) if release_at else None,
        reason=cast(str | None, data["reason"]),
        created_at=datetime.fromisoformat(cast(str, data["created_at"])),
        released_at=datetime.fromisoformat(released_at) if released_at else None,
    )
