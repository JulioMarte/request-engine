from __future__ import annotations

from typing import Any, cast

import pytest
from psycopg import Connection

PgConnection = Connection[Any]


@pytest.mark.postgres
def test_all_revision_managed_aggregates_install_revision_guard(
    admin_conn: PgConnection,
) -> None:
    expected = {
        "representations",
        "requests",
        "capacity_holds",
        "reservations",
        "reservation_attendance",
        "service_queues",
        "queue_entries",
        "waitlist_entries",
        "slot_opportunities",
        "slot_offers",
        "communication_tasks",
        "reminder_plans",
    }
    rows = admin_conn.execute(
        """
        SELECT c.relname
        FROM pg_trigger t
        JOIN pg_class c ON c.oid = t.tgrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'request_engine'
          AND NOT t.tgisinternal
          AND t.tgname LIKE '%_revision_step'
        """
    ).fetchall()
    assert {cast(str, row[0]) for row in rows} == expected
