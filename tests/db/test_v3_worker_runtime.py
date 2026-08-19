from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection, Error

PgConnection = Connection[Any]


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...] = (),
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _organization(conn: PgConnection, label: str) -> UUID:
    suffix = uuid4().hex
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"worker-{label}-{suffix}", f"Worker {label} {suffix}"),
    )


def _principal(conn: PgConnection, organization_id: UUID) -> UUID:
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'human', %s)
        RETURNING id
        """,
        (organization_id, f"operator-{uuid4().hex}"),
    )


def _scheduled_action(
    conn: PgConnection,
    organization_id: UUID,
    *,
    offset: str,
    status: str = "pending",
    attempt_count: int = 0,
    max_attempts: int = 8,
) -> UUID:
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.scheduled_actions (
            organization_id, owner_module, action_type, action_version,
            payload, dedupe_key, execute_at, next_attempt_at,
            status, attempt_count, max_attempts
        ) VALUES (
            %s, 'booking', 'test.worker_action', 1, '{}'::jsonb, %s,
            clock_timestamp() + %s::interval,
            clock_timestamp() + %s::interval,
            %s, %s, %s
        )
        RETURNING id
        """,
        (
            organization_id,
            f"worker-action:{uuid4().hex}",
            offset,
            offset,
            status,
            attempt_count,
            max_attempts,
        ),
    )


def _outbox_message(conn: PgConnection, organization_id: UUID, *, offset: str) -> UUID:
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.outbox_messages (
            organization_id, event_type, payload, next_attempt_at
        ) VALUES (
            %s, 'test.worker_event.v1', '{}'::jsonb,
            clock_timestamp() + %s::interval
        )
        RETURNING id
        """,
        (organization_id, offset),
    )


@pytest.mark.postgres
def test_application_role_cannot_use_cross_tenant_worker_claim_surfaces(
    pg_conninfo: str,
) -> None:
    app_conn: PgConnection = psycopg.connect(pg_conninfo, autocommit=True)
    try:
        app_conn.execute("SET ROLE request_engine_app")
        statements = (
            "SELECT * FROM request_cmd.claim_scheduled_actions(1, interval '30 seconds')",
            "SELECT * FROM request_cmd.claim_outbox_messages(1, interval '30 seconds')",
            "SELECT * FROM request_cmd.claim_provider_events(1, interval '30 seconds')",
        )
        for statement in statements:
            with pytest.raises(Error) as exc_info:
                app_conn.execute(statement).fetchall()
            assert exc_info.value.sqlstate == "42501"
    finally:
        app_conn.close()


@pytest.mark.postgres
def test_worker_role_can_use_cross_tenant_worker_claim_surfaces(pg_conninfo: str) -> None:
    worker_conn: PgConnection = psycopg.connect(pg_conninfo, autocommit=True)
    try:
        worker_conn.execute("SET ROLE request_engine_worker")
        scheduled = worker_conn.execute(
            "SELECT * FROM request_cmd.claim_scheduled_actions(1, interval '30 seconds')"
        ).fetchall()
        outbox = worker_conn.execute(
            "SELECT * FROM request_cmd.claim_outbox_messages(1, interval '30 seconds')"
        ).fetchall()
        provider = worker_conn.execute(
            "SELECT * FROM request_cmd.claim_provider_events(1, interval '30 seconds')"
        ).fetchall()
        assert scheduled == []
        assert outbox == []
        assert provider == []
    finally:
        worker_conn.close()


@pytest.mark.postgres
@pytest.mark.concurrency
def test_scheduled_action_claiming_is_fair_across_tenants(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    hot = _organization(admin_conn, "fair-hot")
    quiet = _organization(admin_conn, "fair-quiet")
    hot_oldest = _scheduled_action(admin_conn, hot, offset="-10 minutes")
    hot_second = _scheduled_action(admin_conn, hot, offset="-9 minutes")
    quiet_oldest = _scheduled_action(admin_conn, quiet, offset="-1 minute")

    worker_conn: PgConnection = psycopg.connect(pg_conninfo, autocommit=True)
    try:
        worker_conn.execute("SET ROLE request_engine_worker")
        rows = worker_conn.execute(
            """
            SELECT action_id, organization_id
            FROM request_cmd.claim_scheduled_actions(500, interval '30 seconds')
            """
        ).fetchall()
    finally:
        worker_conn.close()

    ours = [(cast(UUID, row[0]), cast(UUID, row[1])) for row in rows if row[1] in {hot, quiet}]
    assert ours == [
        (hot_oldest, hot),
        (quiet_oldest, quiet),
        (hot_second, hot),
    ]


@pytest.mark.postgres
@pytest.mark.concurrency
def test_outbox_claiming_is_fair_across_tenants(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    hot = _organization(admin_conn, "outbox-hot")
    quiet = _organization(admin_conn, "outbox-quiet")
    hot_oldest = _outbox_message(admin_conn, hot, offset="-10 minutes")
    hot_second = _outbox_message(admin_conn, hot, offset="-9 minutes")
    quiet_oldest = _outbox_message(admin_conn, quiet, offset="-1 minute")

    worker_conn: PgConnection = psycopg.connect(pg_conninfo, autocommit=True)
    try:
        worker_conn.execute("SET ROLE request_engine_worker")
        rows = worker_conn.execute(
            """
            SELECT message_id, organization_id
            FROM request_cmd.claim_outbox_messages(500, interval '30 seconds')
            """
        ).fetchall()
    finally:
        worker_conn.close()

    ours = [(cast(UUID, row[0]), cast(UUID, row[1])) for row in rows if row[1] in {hot, quiet}]
    assert ours == [
        (hot_oldest, hot),
        (quiet_oldest, quiet),
        (hot_second, hot),
    ]


@pytest.mark.postgres
@pytest.mark.concurrency
def test_scheduled_action_lease_renewal_and_stale_fencing(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    organization_id = _organization(admin_conn, "lease")
    action_id = _scheduled_action(admin_conn, organization_id, offset="-1 minute")
    worker_conn: PgConnection = psycopg.connect(pg_conninfo, autocommit=True)
    try:
        worker_conn.execute("SET ROLE request_engine_worker")
        first = worker_conn.execute(
            """
            SELECT action_id, claim_token
            FROM request_cmd.claim_scheduled_actions(500, interval '30 seconds')
            """
        ).fetchall()
        first_row = next(row for row in first if row[0] == action_id)
        first_token = cast(UUID, first_row[1])
        renewed = worker_conn.execute(
            "SELECT request_cmd.renew_scheduled_action_lease(%s, %s, interval '2 minutes')",
            (action_id, first_token),
        ).fetchone()
        assert renewed == (True,)

        admin_conn.execute(
            """
            UPDATE request_engine.scheduled_actions
            SET lease_until = clock_timestamp() - interval '1 second'
            WHERE id = %s
            """,
            (action_id,),
        )
        stale_renewal = worker_conn.execute(
            "SELECT request_cmd.renew_scheduled_action_lease(%s, %s, interval '2 minutes')",
            (action_id, first_token),
        ).fetchone()
        assert stale_renewal == (False,)

        second = worker_conn.execute(
            """
            SELECT action_id, claim_token
            FROM request_cmd.claim_scheduled_actions(500, interval '30 seconds')
            """
        ).fetchall()
        second_row = next(row for row in second if row[0] == action_id)
        second_token = cast(UUID, second_row[1])
        assert second_token != first_token
        assert worker_conn.execute(
            "SELECT request_cmd.complete_scheduled_action(%s, %s)",
            (action_id, first_token),
        ).fetchone() == (False,)
        assert worker_conn.execute(
            "SELECT request_cmd.complete_scheduled_action(%s, %s)",
            (action_id, second_token),
        ).fetchone() == (True,)
    finally:
        worker_conn.close()


@pytest.mark.postgres
def test_retry_after_uses_database_clock_and_preserves_lifetime_attempt_count(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    organization_id = _organization(admin_conn, "retry")
    action_id = _scheduled_action(admin_conn, organization_id, offset="-1 minute")
    worker_conn: PgConnection = psycopg.connect(pg_conninfo, autocommit=True)
    try:
        worker_conn.execute("SET ROLE request_engine_worker")
        rows = worker_conn.execute(
            """
            SELECT action_id, claim_token, attempt_count
            FROM request_cmd.claim_scheduled_actions(500, interval '30 seconds')
            """
        ).fetchall()
        row = next(value for value in rows if value[0] == action_id)
        claim_token = cast(UUID, row[1])
        assert row[2] == 1
        assert worker_conn.execute(
            """
            SELECT request_cmd.retry_scheduled_action_after(
                %s, %s, interval '90 seconds', 'transient_error'
            )
            """,
            (action_id, claim_token),
        ).fetchone() == ("pending",)
    finally:
        worker_conn.close()

    state = admin_conn.execute(
        """
        SELECT status, attempt_count, max_attempts, last_error_class,
               next_attempt_at > clock_timestamp() + interval '80 seconds'
        FROM request_engine.scheduled_actions
        WHERE id = %s
        """,
        (action_id,),
    ).fetchone()
    assert state == ("pending", 1, 8, "transient_error", True)


@pytest.mark.postgres
def test_admin_replay_is_privileged_preserves_history_and_is_audited(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    organization_id = _organization(admin_conn, "replay")
    actor_id = _principal(admin_conn, organization_id)
    action_id = _scheduled_action(
        admin_conn,
        organization_id,
        offset="-1 minute",
        status="dead",
        attempt_count=8,
        max_attempts=8,
    )
    correlation_id = uuid4()
    runtime_conn: PgConnection = psycopg.connect(pg_conninfo, autocommit=True)
    try:
        runtime_conn.execute("SET ROLE request_engine_worker")
        with pytest.raises(Error) as exc_info:
            runtime_conn.execute(
                """
                SELECT request_admin.replay_dead_scheduled_action(
                    %s, %s, 3, 'worker must not replay'
                )
                """,
                (organization_id, action_id),
            ).fetchone()
        assert exc_info.value.sqlstate == "42501"

        runtime_conn.execute("RESET ROLE")
        runtime_conn.execute("SET ROLE request_engine_admin")
        for key, value in {
            "request_engine.organization_id": str(organization_id),
            "request_engine.authenticated_principal_id": str(actor_id),
            "request_engine.principal_kind": "human",
            "request_engine.authentication_method": "test_admin_adapter",
            "request_engine.correlation_id": str(correlation_id),
        }.items():
            runtime_conn.execute("SELECT set_config(%s, %s, false)", (key, value))
        replayed = runtime_conn.execute(
            """
            SELECT request_admin.replay_dead_scheduled_action(
                %s, %s, 3, 'operator approved replay'
            )
            """,
            (organization_id, action_id),
        ).fetchone()
    finally:
        runtime_conn.close()

    assert replayed == (True,)
    state = admin_conn.execute(
        """
        SELECT status, attempt_count, max_attempts, replay_count,
               last_replayed_at IS NOT NULL
        FROM request_engine.scheduled_actions
        WHERE organization_id = %s AND id = %s
        """,
        (organization_id, action_id),
    ).fetchone()
    assert state == ("pending", 8, 11, 1, True)
    audit = admin_conn.execute(
        """
        SELECT command_name, actor_principal_id, details->>'reason',
               correlation_data->>'correlation_id'
        FROM request_engine.audit_records
        WHERE organization_id = %s
          AND aggregate_kind = 'ScheduledAction'
          AND aggregate_id = %s
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (organization_id, action_id),
    ).fetchone()
    assert audit == (
        "admin.replay_scheduled_action",
        actor_id,
        "operator approved replay",
        str(correlation_id),
    )


@pytest.mark.postgres
def test_provider_event_rejected_and_dead_are_distinct(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    organization_id = _organization(admin_conn, "provider-terminal")
    rejected_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.provider_events (
            organization_id, provider_key, connection_key,
            provider_event_id, payload_hash, payload,
            next_attempt_at
        ) VALUES (
            %s, 'fake', 'primary', %s, 'hash-a', '{}'::jsonb,
            '2000-01-01 00:00:00+00'
        )
        RETURNING id
        """,
        (organization_id, f"rejected-{uuid4().hex}"),
    )
    dead_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.provider_events (
            organization_id, provider_key, connection_key,
            provider_event_id, payload_hash, payload,
            next_attempt_at
        ) VALUES (
            %s, 'fake', 'primary', %s, 'hash-b', '{}'::jsonb,
            '2000-01-01 00:00:01+00'
        )
        RETURNING id
        """,
        (organization_id, f"dead-{uuid4().hex}"),
    )
    worker_conn: PgConnection = psycopg.connect(pg_conninfo, autocommit=True)
    try:
        worker_conn.execute("SET ROLE request_engine_worker")
        rows = worker_conn.execute(
            """
            SELECT provider_event_row_id, claim_token
            FROM request_cmd.claim_provider_events(500, interval '30 seconds')
            """
        ).fetchall()
        tokens = {cast(UUID, row[0]): cast(UUID, row[1]) for row in rows}
        assert worker_conn.execute(
            "SELECT request_cmd.reject_provider_event(%s, %s, 'invalid_payload')",
            (rejected_id, tokens[rejected_id]),
        ).fetchone() == (True,)
        assert worker_conn.execute(
            "SELECT request_cmd.dead_letter_provider_event(%s, %s, 'handler_missing')",
            (dead_id, tokens[dead_id]),
        ).fetchone() == (True,)
    finally:
        worker_conn.close()

    states = dict(
        admin_conn.execute(
            "SELECT id, status FROM request_engine.provider_events WHERE id IN (%s, %s)",
            (rejected_id, dead_id),
        ).fetchall()
    )
    assert states == {rejected_id: "rejected", dead_id: "dead"}
