from typing import cast
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.queue.adapters.db.subject_authority import require_subject_authority
from request_engine.modules.queue.contracts.live_capacity import CustomerQueueProjectionTarget
from request_engine.platform.db.read_snapshot import postgres_snapshot_session
from request_engine.platform.db.read_snapshot_types import ReadSnapshot


async def read_customer_projection_target(
    snapshot: ReadSnapshot,
    *,
    organization_id: UUID,
    principal_id: UUID,
    queue_id: UUID,
    subject_party_id: UUID,
    allow_subject_override: bool,
) -> CustomerQueueProjectionTarget | None:
    session = postgres_snapshot_session(snapshot)
    await require_subject_authority(
        session,
        organization_id=organization_id,
        principal_id=principal_id,
        subject_party_id=subject_party_id,
        scope_key="queue.manage",
        allow_operator_override=allow_subject_override,
        lock_authority=False,
    )
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT id, admitted_at, status
                    FROM request_engine.queue_entries
                    WHERE organization_id = :organization_id
                      AND service_queue_id = :queue_id
                      AND subject_party_id = :subject_party_id
                      AND status IN ('waiting','called','serving')
                    ORDER BY admitted_at DESC, id DESC
                    LIMIT 1
                    """
                ),
                {
                    "organization_id": organization_id,
                    "queue_id": queue_id,
                    "subject_party_id": subject_party_id,
                },
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    status = cast(str, row["status"])
    if status == "waiting":
        entries_ahead = cast(
            int,
            await session.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM request_engine.queue_entries
                    WHERE organization_id = :organization_id
                      AND service_queue_id = :queue_id
                      AND status = 'waiting'
                      AND (admitted_at, id) < (:admitted_at, :entry_id)
                    """
                ),
                {
                    "organization_id": organization_id,
                    "queue_id": queue_id,
                    "admitted_at": row["admitted_at"],
                    "entry_id": row["id"],
                },
            ),
        )
    else:
        entries_ahead = 0
    return CustomerQueueProjectionTarget(
        queue_entry_id=cast(UUID, row["id"]),
        entries_ahead=entries_ahead,
    )
