from datetime import datetime
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.queue.adapters.db.live_queue_mapping import staff_entry_from_row
from request_engine.modules.queue.contracts.live_queue import StaffQueueHistoryPage
from request_engine.platform.db.session import SessionFactory, tenant_transaction


async def read_staff_queue_history(
    session_factory: SessionFactory,
    organization_id: UUID,
    queue_id: UUID,
    *,
    window_start: datetime,
    window_end: datetime,
    limit: int,
    cursor: UUID | None,
) -> StaffQueueHistoryPage:
    async with tenant_transaction(session_factory, organization_id) as session:
        rows = (
            (
                await session.execute(
                    text(
                        """
                        WITH cursor_row AS (
                            SELECT admitted_at, queue_entry_id
                              FROM request_read.live_service_staff_v1
                             WHERE organization_id=:organization_id
                               AND queue_id=:queue_id
                               AND queue_entry_id=:cursor
                        )
                        SELECT queue_entry_id, queue_id, subject_party_id,
                               subject_display_name, reservation_id, status,
                               scheduled_at, arrived_at, admitted_at, called_at,
                               expected_workload_key, service_session_id,
                               service_status, actual_resource_id, actual_location_id,
                               actual_workload_key, service_started_at,
                               service_completed_at,
                               FALSE AS recall_eligible,
                               NULL::uuid AS recall_hold_id,
                               NULL::text AS recall_hold_kind,
                               NULL::timestamptz AS recall_hold_until_at,
                               NULL::text AS recall_hold_event_key,
                               NULL::text AS recall_hold_reason,
                               NULL::text AS active_skip_reason,
                               queue_revision, service_revision
                          FROM request_read.live_service_staff_v1
                         WHERE organization_id=:organization_id
                           AND queue_id=:queue_id
                           AND queue_entry_id IS NOT NULL
                           AND status IN ('completed','no_show','cancelled')
                           AND admitted_at >= :window_start
                           AND admitted_at < :window_end
                           AND (
                               :cursor IS NULL OR
                               (admitted_at, queue_entry_id) > (
                                   SELECT admitted_at, queue_entry_id FROM cursor_row
                               )
                           )
                         ORDER BY admitted_at, queue_entry_id
                         LIMIT :row_limit
                        """
                    ),
                    {
                        "organization_id": organization_id,
                        "queue_id": queue_id,
                        "window_start": window_start,
                        "window_end": window_end,
                        "cursor": cursor,
                        "row_limit": limit + 1,
                    },
                )
            )
            .mappings()
            .all()
        )
    has_more = len(rows) > limit
    visible = rows[:limit]
    entries = tuple(staff_entry_from_row(row) for row in visible)
    next_cursor = entries[-1].queue_entry_id if has_more and entries else None
    return StaffQueueHistoryPage(entries=entries, next_cursor=next_cursor)
