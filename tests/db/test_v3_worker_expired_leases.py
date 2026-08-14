from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection

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
        (f"expired-lease-{suffix}", f"Expired lease {suffix}"),
    )


def _expire(conn: PgConnection, table: str, work_id: UUID) -> None:
    if table not in {"scheduled_actions", "outbox_messages", "provider_events"}:
        raise ValueError("unsupported worker table")
    conn.execute(
        f"""
        UPDATE request_engine.{table}
        SET lease_until = clock_timestamp() - interval '1 second'
        WHERE id = %s
        """,  # noqa: S608 - table is selected from a fixed local allowlist.
        (work_id,),
    )


@pytest.mark.postgres
@pytest.mark.concurrency
def test_expired_scheduled_action_token_cannot_finalize_without_reclaim(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    organization_id = _organization(admin_conn)
    action_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.scheduled_actions (
            organization_id, owner_module, action_type, payload,
            dedupe_key, execute_at, next_attempt_at
        ) VALUES (
            %s, 'booking', 'test.expired', '{}'::jsonb, %s,
            '2000-01-01 00:00:00+00', '2000-01-01 00:00:00+00'
        )
        RETURNING id
        """,
        (organization_id, f"expired:{uuid4().hex}"),
    )
    worker: PgConnection = psycopg.connect(pg_conninfo, autocommit=True)
    try:
        worker.execute("SET ROLE request_engine_worker")
        rows = worker.execute(
            """
            SELECT action_id, claim_token
            FROM request_cmd.claim_scheduled_actions(500, interval '30 seconds')
            """
        ).fetchall()
        token = cast(UUID, next(row[1] for row in rows if row[0] == action_id))
        _expire(admin_conn, "scheduled_actions", action_id)

        assert worker.execute(
            "SELECT request_cmd.complete_scheduled_action(%s, %s)",
            (action_id, token),
        ).fetchone() == (False,)
        assert worker.execute(
            """
            SELECT request_cmd.retry_scheduled_action_after(
                %s, %s, interval '1 second', 'late_retry'
            )
            """,
            (action_id, token),
        ).fetchone() == ("stale",)
        assert worker.execute(
            "SELECT request_cmd.dead_letter_scheduled_action(%s, %s, 'late_dead')",
            (action_id, token),
        ).fetchone() == (False,)
    finally:
        worker.close()

    assert admin_conn.execute(
        "SELECT status FROM request_engine.scheduled_actions WHERE id = %s",
        (action_id,),
    ).fetchone() == ("leased",)


@pytest.mark.postgres
@pytest.mark.concurrency
def test_expired_outbox_token_cannot_finalize_without_reclaim(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    organization_id = _organization(admin_conn)
    message_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.outbox_messages (
            organization_id, event_type, payload, next_attempt_at
        ) VALUES (%s, 'test.expired.v1', '{}'::jsonb, '2000-01-01 00:00:00+00')
        RETURNING id
        """,
        (organization_id,),
    )
    worker: PgConnection = psycopg.connect(pg_conninfo, autocommit=True)
    try:
        worker.execute("SET ROLE request_engine_worker")
        rows = worker.execute(
            """
            SELECT message_id, claim_token
            FROM request_cmd.claim_outbox_messages(500, interval '30 seconds')
            """
        ).fetchall()
        token = cast(UUID, next(row[1] for row in rows if row[0] == message_id))
        _expire(admin_conn, "outbox_messages", message_id)

        assert worker.execute(
            "SELECT request_cmd.complete_outbox_message(%s, %s)",
            (message_id, token),
        ).fetchone() == (False,)
        assert worker.execute(
            """
            SELECT request_cmd.retry_outbox_message_after(
                %s, %s, interval '1 second', 'late_retry'
            )
            """,
            (message_id, token),
        ).fetchone() == ("stale",)
        assert worker.execute(
            "SELECT request_cmd.dead_letter_outbox_message(%s, %s, 'late_dead')",
            (message_id, token),
        ).fetchone() == (False,)
    finally:
        worker.close()

    assert admin_conn.execute(
        "SELECT status FROM request_engine.outbox_messages WHERE id = %s",
        (message_id,),
    ).fetchone() == ("leased",)


@pytest.mark.postgres
@pytest.mark.concurrency
def test_expired_provider_event_token_cannot_finalize_without_reclaim(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    organization_id = _organization(admin_conn)
    event_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.provider_events (
            organization_id, provider_key, connection_key,
            provider_event_id, payload_hash, payload, next_attempt_at
        ) VALUES (
            %s, 'fake', 'primary', %s, 'hash', '{}'::jsonb,
            '2000-01-01 00:00:00+00'
        )
        RETURNING id
        """,
        (organization_id, f"expired-{uuid4().hex}"),
    )
    worker: PgConnection = psycopg.connect(pg_conninfo, autocommit=True)
    try:
        worker.execute("SET ROLE request_engine_worker")
        rows = worker.execute(
            """
            SELECT provider_event_row_id, claim_token
            FROM request_cmd.claim_provider_events(500, interval '30 seconds')
            """
        ).fetchall()
        token = cast(UUID, next(row[1] for row in rows if row[0] == event_id))
        _expire(admin_conn, "provider_events", event_id)

        assert worker.execute(
            "SELECT request_cmd.complete_provider_event(%s, %s)",
            (event_id, token),
        ).fetchone() == (False,)
        assert worker.execute(
            """
            SELECT request_cmd.retry_provider_event_after(
                %s, %s, interval '1 second', 'late_retry'
            )
            """,
            (event_id, token),
        ).fetchone() == ("stale",)
        assert worker.execute(
            "SELECT request_cmd.reject_provider_event(%s, %s, 'late_reject')",
            (event_id, token),
        ).fetchone() == (False,)
        assert worker.execute(
            "SELECT request_cmd.dead_letter_provider_event(%s, %s, 'late_dead')",
            (event_id, token),
        ).fetchone() == (False,)
    finally:
        worker.close()

    assert admin_conn.execute(
        "SELECT status FROM request_engine.provider_events WHERE id = %s",
        (event_id,),
    ).fetchone() == ("leased",)
