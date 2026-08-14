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
            organization_id,
            owner_module,
            action_type,
            action_version,
            payload,
            dedupe_key,
            execute_at,
            next_attempt_at,
            status,
            attempt_count,
            max_attempts
        ) VALUES (
            %s,
            'booking',
            'test.worker_action',
            1,
            '{}'::jsonb,
            %s,
            clock_timestamp() + %s::interval,
            clock_timestamp() + %s::interval,
            %s,
            %s,
            %s
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
        worker_conn.execute(
            "SELECT * FROM request_cmd.claim_scheduled_actions(1, interval '30 seconds')"
        ).fetchall()
        worker_conn.execute(
            "SELECT * FROM request_cmd.claim_outbox_messages(1, interval '30 seconds')"
        ).fetchall()
        worker_conn.execute(
            "SELECT * FROM request_cmd.claim_provider_events(1, interval '30 seconds')"
        ).fetchall()
    finally:
        worker_conn.close()


@pytest.mark.postgres
@pytest.mark.concurrency
def test_scheduled_action_claiming_is_fair_across_tenants(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    first_org = _organization(admin_conn, "fair-a")
    second_org = _organization(admin_conn, "fair-b")
    first_oldest = _scheduled_action(admin_conn, first_org, offset="-10 minutes")
    first_second = _scheduled_action(admin_conn, first_org, offset="-9 minutes")
    second_oldest = _scheduled_action(admin_conn, second_org, offset="-1 minute")

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

    ours = [
        (cast(UUID, row[0]), cast(UUID, row[1]))
        for row in rows
        if row[1] in {first_org, second_org}
    ]
    assert ours == [
        (first_oldest, first_org),
        (second_oldest, second_org),
        (first_second, first_org),
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

        stale_complete = worker_conn.execute(
            "SELECT request_cmd.complete_scheduled_action(%s, %s)",
            (action_id, first_token),
        ).fetchone()
        current_complete = worker_conn.execute(
            "SELECT request_cmd.complete_scheduled_action(%s, %s)",
            (action_id, second_token),
        ).fetchone()
        assert stale_complete == (False,)
        assert current_complete == (True,)
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

        retry = worker_conn.execute(
            """
            SELECT request_cmd.retry_scheduled_action_after(
                %s, %s, interval '90 seconds', 'transient_error'
            )
            """,
            (action_id, claim_token),
        ).fetchone()
        assert retry == ("pending",)
    finally:
        worker_conn.close()

    state = admin_conn.execute(
        """
        SELECT status,
               attempt_count,
               max_attempts,
               last_error_class,
               next_attempt_at > clock_timestamp() + interval '80 seconds'
        FROM request_engine.scheduled_actions
        WHERE id = %s
        """,
        (action_id,),
    ).fetchone()
    assert state == ("pending", 1, 8, "transient_error", True)


@pytest.mark.postgres
def test_admin_replay_is_explicit_bounded_and_audited(admin_conn: PgConnection) -> None:
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

    replayed = admin_conn.execute(
        """
        SELECT request_admin.replay_dead_scheduled_action(%s, %s, %s, 3, %s)
        """,
        (organization_id, action_id, actor_id, "operator approved replay"),
    ).fetchone()
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
        SELECT command_name, actor_principal_id, details->>'reason'
        FROM request_engine.audit_records
        WHERE organization_id = %s
          AND aggregate_kind = 'ScheduledAction'
          AND aggregate_id = %s
        ORDER BY occurred_at DESC, id DESC
        LIMIT 1
        """,
        (organization_id, action_id),
    ).fetchone()
    assert audit == ("admin.replay_scheduled_action", actor_id, "operator approved replay")
