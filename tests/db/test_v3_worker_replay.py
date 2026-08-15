from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection, Error

PgConnection = Connection[tuple[Any, ...]]


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...] = (),
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _create_organization(conn: PgConnection) -> UUID:
    suffix = uuid4().hex
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"replay-{suffix}", f"Worker Replay Test {suffix}"),
    )


@pytest.mark.postgres
def test_dead_letter_replay_is_admin_only_and_audited(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    organization_id = _create_organization(admin_conn)
    action_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.scheduled_actions (
            organization_id,
            owner_module,
            action_type,
            dedupe_key,
            execute_at,
            next_attempt_at,
            status,
            attempt_count,
            max_attempts,
            last_error_class
        ) VALUES (
            %s,
            'communications',
            'test_replay',
            %s,
            clock_timestamp(),
            clock_timestamp(),
            'dead',
            8,
            8,
            'PoisonMessage'
        )
        RETURNING id
        """,
        (organization_id, f"scheduled-{uuid4().hex}"),
    )
    message_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.outbox_messages (
            organization_id,
            event_type,
            payload,
            status,
            attempt_count,
            max_attempts,
            last_error_class
        ) VALUES (
            %s,
            'test.replay.v1',
            '{}'::jsonb,
            'dead',
            12,
            12,
            'ProviderFailure'
        )
        RETURNING id
        """,
        (organization_id,),
    )

    worker: PgConnection = psycopg.connect(pg_conninfo, autocommit=True)
    try:
        worker.execute("SET ROLE request_engine_worker")
        with pytest.raises(Error) as scheduled_denied:
            worker.execute(
                """
                SELECT request_cmd.replay_scheduled_action(
                    %s, clock_timestamp(), 'worker must not replay'
                )
                """,
                (action_id,),
            ).fetchone()
        assert scheduled_denied.value.sqlstate == "42501"

        with pytest.raises(Error) as outbox_denied:
            worker.execute(
                """
                SELECT request_cmd.replay_outbox_message(
                    %s, clock_timestamp(), 'worker must not replay'
                )
                """,
                (message_id,),
            ).fetchone()
        assert outbox_denied.value.sqlstate == "42501"
    finally:
        worker.close()

    operator: PgConnection = psycopg.connect(pg_conninfo, autocommit=True)
    try:
        operator.execute("SET ROLE request_engine_admin")
        scheduled_replayed = operator.execute(
            """
            SELECT request_cmd.replay_scheduled_action(
                %s, clock_timestamp(), 'operator approved retry'
            )
            """,
            (action_id,),
        ).fetchone()
        assert scheduled_replayed == (True,)

        outbox_replayed = operator.execute(
            """
            SELECT request_cmd.replay_outbox_message(
                %s, clock_timestamp(), 'provider recovered'
            )
            """,
            (message_id,),
        ).fetchone()
        assert outbox_replayed == (True,)
    finally:
        operator.close()

    action = admin_conn.execute(
        """
        SELECT status, attempt_count, claim_token, lease_until, last_error_class
        FROM request_engine.scheduled_actions
        WHERE id = %s
        """,
        (action_id,),
    ).fetchone()
    assert action == ("pending", 0, None, None, None)

    message = admin_conn.execute(
        """
        SELECT status, attempt_count, claim_token, lease_until, last_error_class
        FROM request_engine.outbox_messages
        WHERE id = %s
        """,
        (message_id,),
    ).fetchone()
    assert message == ("pending", 0, None, None, None)

    audit_rows = admin_conn.execute(
        """
        SELECT command_name, aggregate_kind, aggregate_id, details ->> 'reason'
        FROM request_engine.audit_records
        WHERE organization_id = %s
          AND aggregate_id IN (%s, %s)
        ORDER BY command_name
        """,
        (organization_id, action_id, message_id),
    ).fetchall()
    assert audit_rows == [
        (
            "worker.replay_outbox_message",
            "OutboxMessage",
            message_id,
            "provider recovered",
        ),
        (
            "worker.replay_scheduled_action",
            "ScheduledAction",
            action_id,
            "operator approved retry",
        ),
    ]

    admin_conn.execute("SET ROLE request_engine_admin")
    try:
        second_replay = admin_conn.execute(
            """
            SELECT request_cmd.replay_scheduled_action(
                %s, clock_timestamp(), 'must remain terminal-only'
            )
            """,
            (action_id,),
        ).fetchone()
        assert second_replay == (False,)
    finally:
        admin_conn.execute("RESET ROLE")
