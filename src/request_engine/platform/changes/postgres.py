"""Tenant-scoped snapshot-delta reads of committed outbox facts."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text

from request_engine.platform.changes.model import FeedRow, FeedSnapshot
from request_engine.platform.db.session import SessionFactory, tenant_transaction

# One statement: the snapshot returned and the rows read share the statement
# snapshot (READ COMMITTED takes one snapshot per statement and the view is
# not volatile), so "visible in the returned snapshot" == "read here".
_READ_SINCE = text(
    """
    WITH current_snapshot AS (
        SELECT pg_current_snapshot() AS snapshot, statement_timestamp() AS taken_at
    )
    SELECT current_snapshot.snapshot::text AS snapshot,
           current_snapshot.taken_at,
           fact.event_id,
           fact.event_type,
           fact.aggregate_kind,
           fact.aggregate_id,
           fact.change_xid::text AS change_xid,
           fact.occurred_at,
           fact.queue_id,
           fact.location_id,
           fact.business_date,
           fact.reservation_id
      FROM current_snapshot
      LEFT JOIN LATERAL (
            SELECT feed.*
              FROM request_read.change_feed_v1 feed
             WHERE feed.organization_id = :organization_id
               AND feed.change_xid >= pg_snapshot_xmin(CAST(CAST(:after AS text) AS pg_snapshot))
               AND NOT pg_visible_in_snapshot(
                       feed.change_xid, CAST(CAST(:after AS text) AS pg_snapshot)
                   )
               AND feed.event_type LIKE ANY (CAST(:patterns AS text[]))
             ORDER BY feed.event_id
             LIMIT :limit
           ) fact ON true
    """
)
_CURRENT_SNAPSHOT = text(
    "SELECT pg_current_snapshot()::text AS snapshot, statement_timestamp() AS taken_at"
)


@dataclass(frozen=True, slots=True)
class FeedDelta:
    rows: tuple[FeedRow, ...]
    snapshot: FeedSnapshot


class PostgresChangeFeedReader:
    """Read the facts of one organization committed after a snapshot.

    Runs under the runtime role with the tenant bound, so the invoker view's RLS
    and the explicit organization equality both restrict the result. No row
    locks are taken and no network I/O happens inside the transaction.
    """

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def current_snapshot(self, organization_id: UUID) -> FeedSnapshot:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            row = (await session.execute(_CURRENT_SNAPSHOT)).one()
        return FeedSnapshot(snapshot=cast(str, row.snapshot), taken_at=row.taken_at)

    async def read_since(
        self,
        organization_id: UUID,
        after: FeedSnapshot,
        *,
        patterns: Sequence[str],
        limit: int,
    ) -> FeedDelta:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            await session.execute(text("SET LOCAL statement_timeout = '5s'"))
            result = await session.execute(
                _READ_SINCE,
                {
                    "organization_id": organization_id,
                    "after": after.snapshot,
                    "patterns": list(patterns),
                    "limit": limit,
                },
            )
            records = result.all()
        snapshot = FeedSnapshot(
            snapshot=cast(str, records[0].snapshot), taken_at=records[0].taken_at
        )
        rows = tuple(
            FeedRow(
                event_id=cast(UUID, record.event_id),
                event_type=cast(str, record.event_type),
                aggregate_kind=cast(str | None, record.aggregate_kind),
                aggregate_id=cast(UUID | None, record.aggregate_id),
                change_xid=int(cast(str, record.change_xid)),
                occurred_at=cast(datetime, record.occurred_at),
                queue_id=cast(UUID | None, record.queue_id),
                location_id=cast(UUID | None, record.location_id),
                business_date=cast(date | None, record.business_date),
                reservation_id=cast(UUID | None, record.reservation_id),
            )
            for record in records
            if record.event_id is not None
        )
        return FeedDelta(rows=rows, snapshot=snapshot)
