from datetime import UTC, datetime, timedelta
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.modules.communications.adapters.db.reminder_commands import (
    REMINDER_ACTION_TYPE,
    REMINDER_ACTION_VERSION,
)
from request_engine.modules.communications.adapters.db.reminder_occurrences import (
    PostgresReminderOccurrenceCommands,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.scheduling.postgres import ScheduledActionLease
from request_engine.platform.worker.runtime import LeaseLostWorkError

PgConnection = Connection[Any]


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...] = (),
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _organization(conn: PgConnection) -> UUID:
    suffix = uuid4().hex
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"reminder-fence-{suffix}", f"Reminder Fence {suffix}"),
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_reminder_materialization_requires_current_claim_before_domain_write(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    organization_id = _organization(admin_conn)
    reminder_plan_id = uuid4()
    occurrence_at = datetime.now(UTC) - timedelta(minutes=1)
    stale_lease = ScheduledActionLease(
        id=uuid4(),
        organization_id=organization_id,
        claim_token=uuid4(),
        owner_module="communications",
        action_type=REMINDER_ACTION_TYPE,
        action_version=REMINDER_ACTION_VERSION,
        subject_kind="ReminderPlan",
        subject_id=reminder_plan_id,
        payload={
            "reminder_plan_id": str(reminder_plan_id),
            "occurrence_at": occurrence_at.isoformat(),
        },
        attempt_count=1,
        lease_until=datetime.now(UTC) + timedelta(seconds=30),
    )

    commands = PostgresReminderOccurrenceCommands(app_session_factory)

    with pytest.raises(LeaseLostWorkError, match="reminder_materialization_fence_lost"):
        await commands.materialize(stale_lease)
