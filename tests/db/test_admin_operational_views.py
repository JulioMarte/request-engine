from __future__ import annotations

import pytest

pytestmark = [pytest.mark.postgres]


_REMOVED_ADMIN_VIEWS = (
    "outbox_health_v1",
    "scheduled_action_health_v1",
)


def test_only_supported_worker_admin_projection_remains(db_conn) -> None:
    rows = db_conn.execute(
        """
        SELECT c.relname
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'request_admin'
          AND c.relkind = 'v'
        ORDER BY c.relname
        """
    ).fetchall()

    names = [row[0] for row in rows]
    assert "worker_dead_letters_v1" in names
    for removed in _REMOVED_ADMIN_VIEWS:
        assert removed not in names


def test_worker_dead_letters_projection_still_covers_all_worker_families(db_conn) -> None:
    definition = db_conn.execute(
        "SELECT pg_get_viewdef('request_admin.worker_dead_letters_v1'::regclass, true)"
    ).fetchone()[0]

    assert "scheduled_actions" in definition
    assert "outbox_messages" in definition
    assert "provider_events" in definition
    assert "'scheduled_action'::text" in definition
    assert "'outbox_message'::text" in definition
    assert "'provider_event'::text" in definition
