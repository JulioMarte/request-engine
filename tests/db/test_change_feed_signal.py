"""PostgreSQL producer side of the change feed (migration 0046, ADR 0020).

Protected guarantees: an outbox append signals only after COMMIT (never for a
rollback), the signal carries only ``<organization_id>:<xid8>`` matching the
fact's ``change_xid``, one statement signals once per organization, and the
``request_read.change_feed_v1`` read contract is invoker-RLS tenant-opaque,
payload-free and read-only for the runtime role.

Plausible regressions caught: a row-level trigger flooding one notify per row,
payload/event data in the notification, ``change_xid`` not matching the
signalling transaction, the view losing ``security_invoker`` (definer rights
would bypass outbox RLS), exposing ``payload``, or granting writes/PUBLIC.
Boundary: a release-shaped app LOGIN for writes/reads, an independent admin
connection as LISTEN oracle.
"""

import json
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection

pytestmark = [pytest.mark.postgres, pytest.mark.integration, pytest.mark.security]

PgConnection = Connection[Any]


def _organization(admin_conn: PgConnection) -> UUID:
    key = f"feed-{uuid4().hex[:12]}"
    row = admin_conn.execute(
        "INSERT INTO request_engine.organizations (organization_key, display_name, public_profile)"
        " VALUES (%s, %s, %s) RETURNING id",
        (key, key, json.dumps({})),
    ).fetchone()
    assert row is not None
    return UUID(str(row[0]))


def _append(conn: PgConnection, organization_id: UUID, *, count: int = 1) -> list[int]:
    conn.execute(
        "SELECT set_config('request_engine.organization_id', %s, true)", (str(organization_id),)
    )
    rows = conn.execute(
        "INSERT INTO request_engine.outbox_messages "
        "(organization_id, event_type, aggregate_kind, aggregate_id, payload) "
        "SELECT %s, 'reservation.created.v1', 'Reservation', gen_random_uuid(), "
        "jsonb_build_object('display_name', 'Ana Secreta', 'phone', '+18095550199') "
        "FROM generate_series(1, %s) RETURNING change_xid::text",
        (organization_id, count),
    ).fetchall()
    return [int(row[0]) for row in rows]


def _notifications(listener: PgConnection, *, stop_after: int) -> list[str]:
    return [
        item.payload
        for item in listener.notifies(timeout=10, stop_after=stop_after)
        if item.channel == "request_engine_changes"
    ]


def test_signal_is_commit_only_payload_free_and_once_per_statement_organization(
    admin_conn: PgConnection, pg_conninfo: str, app_role_conn: PgConnection
) -> None:
    org_a, org_b = _organization(admin_conn), _organization(admin_conn)
    listener: PgConnection = psycopg.connect(pg_conninfo, autocommit=True)
    try:
        listener.execute("LISTEN request_engine_changes")

        _append(app_role_conn, org_a)
        app_role_conn.rollback()  # never committed: no signal may exist for it

        xids = _append(app_role_conn, org_b, count=3)
        app_role_conn.commit()
        assert len(set(xids)) == 1  # one transaction, one change_xid

        # The first (and only) signal is the committed one: once for 3 rows.
        assert _notifications(listener, stop_after=1) == [f"{org_b}:{xids[0]}"]
        assert list(listener.notifies(timeout=0.5)) == []
    finally:
        listener.close()

    leaked = admin_conn.execute(
        "SELECT count(*) FROM request_engine.outbox_messages WHERE organization_id = %s",
        (org_a,),
    ).fetchone()
    assert leaked == (0,)


def test_feed_view_is_invoker_rls_opaque_and_payload_free(
    admin_conn: PgConnection, app_role_conn: PgConnection
) -> None:
    org_a, org_b = _organization(admin_conn), _organization(admin_conn)
    _append(app_role_conn, org_a, count=2)
    app_role_conn.commit()

    app_role_conn.execute(
        "SELECT set_config('request_engine.organization_id', %s, true)", (str(org_b),)
    )
    foreign = app_role_conn.execute(
        "SELECT count(*) FROM request_read.change_feed_v1 WHERE organization_id = %s", (org_a,)
    ).fetchone()
    app_role_conn.rollback()
    assert foreign == (0,)

    app_role_conn.execute(
        "SELECT set_config('request_engine.organization_id', %s, true)",
        (
            str(
                org_a,
            ),
        ),
    )
    cursor = app_role_conn.execute("SELECT * FROM request_read.change_feed_v1")
    own = cursor.fetchall()
    columns = [column.name for column in cursor.description or ()]
    app_role_conn.rollback()
    assert len(own) == 2
    assert columns == [
        "organization_id",
        "event_id",
        "event_type",
        "aggregate_kind",
        "aggregate_id",
        "change_xid",
        "occurred_at",
        "queue_id",
        "location_id",
        "business_date",
        "reservation_id",
    ]
    assert "Ana Secreta" not in repr(own) and "+18095550199" not in repr(own)

    row = admin_conn.execute(
        """
        SELECT c.reloptions, pg_catalog.pg_get_userbyid(c.relowner),
               has_table_privilege('request_engine_app', c.oid, 'SELECT'),
               has_table_privilege('request_engine_app', c.oid, 'INSERT'),
               has_table_privilege('public', c.oid, 'SELECT'),
               (SELECT p.prosecdef FROM pg_catalog.pg_proc p
                 WHERE p.oid = 'request_engine.notify_outbox_change'::regproc)
          FROM pg_catalog.pg_class c
          JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'request_read' AND c.relname = 'change_feed_v1'
        """
    ).fetchone()
    assert row is not None
    options, owner, can_select, can_insert, public_select, definer = row
    assert "security_invoker=true" in (options or [])
    assert owner == "request_engine_schema_owner"
    assert (can_select, can_insert, public_select, definer) == (True, False, False, False)
