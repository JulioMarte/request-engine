from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection, Error

PgConnection = Connection[tuple[Any, ...]]


def _uuid_row(
    conn: PgConnection,
    sql: str,
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
        (f"platform-{suffix}", f"Platform Test {suffix}"),
    )


@pytest.mark.postgres
def test_idempotency_replays_same_fingerprint_and_rejects_key_reuse(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    organization_id = _create_organization(admin_conn)
    principal_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'integration', %s)
        RETURNING id
        """,
        (organization_id, f"principal-{uuid4().hex}"),
    )
    idem_key = f"idem-{uuid4().hex}"

    app_conn: PgConnection = psycopg.connect(pg_conninfo)
    try:
        app_conn.execute("SET ROLE request_engine_app")

        with app_conn.transaction():
            app_conn.execute(
                "SELECT set_config('request_engine.organization_id', %s, true)",
                (str(organization_id),),
            )
            first = app_conn.execute(
                """
                SELECT idempotency_id, status, replay
                FROM request_cmd.acquire_idempotency(%s, %s, %s, %s, %s)
                """,
                (
                    organization_id,
                    principal_id,
                    "appointments.book",
                    idem_key,
                    "fingerprint-a",
                ),
            ).fetchone()
            assert first is not None
            first_id = cast(UUID, first[0])
            assert first[1:] == ("in_progress", False)

            completed = app_conn.execute(
                "SELECT request_cmd.complete_idempotency(%s, %s::jsonb)",
                (first_id, '{"reservation_id":"opaque"}'),
            ).fetchone()
            assert completed is not None
            assert completed[0] is True

        with app_conn.transaction():
            app_conn.execute(
                "SELECT set_config('request_engine.organization_id', %s, true)",
                (str(organization_id),),
            )
            replay = app_conn.execute(
                """
                SELECT idempotency_id, status, replay, result_data
                FROM request_cmd.acquire_idempotency(%s, %s, %s, %s, %s)
                """,
                (
                    organization_id,
                    principal_id,
                    "appointments.book",
                    idem_key,
                    "fingerprint-a",
                ),
            ).fetchone()
            assert replay is not None
            assert replay[0] == first_id
            assert replay[1] == "completed"
            assert replay[2] is True
            assert replay[3] == {"reservation_id": "opaque"}

        with pytest.raises(Error) as exc_info, app_conn.transaction():
            app_conn.execute(
                "SELECT set_config('request_engine.organization_id', %s, true)",
                (str(organization_id),),
            )
            app_conn.execute(
                """
                SELECT *
                FROM request_cmd.acquire_idempotency(%s, %s, %s, %s, %s)
                """,
                (
                    organization_id,
                    principal_id,
                    "appointments.book",
                    idem_key,
                    "fingerprint-different",
                ),
            ).fetchall()
        assert exc_info.value.sqlstate == "23505"
    finally:
        app_conn.close()


@pytest.mark.postgres
@pytest.mark.concurrency
def test_outbox_fencing_rejects_stale_worker(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    organization_id = _create_organization(admin_conn)
    message_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.outbox_messages (
            organization_id,
            event_type,
            schema_version,
            payload,
            next_attempt_at
        ) VALUES (%s, 'request.created.v1', 1, '{}'::jsonb, clock_timestamp())
        RETURNING id
        """,
        (organization_id,),
    )

    worker: PgConnection = psycopg.connect(pg_conninfo, autocommit=True)
    try:
        worker.execute("SET ROLE request_engine_worker")
        first = worker.execute(
            """
            SELECT message_id, organization_id, claim_token
            FROM request_cmd.claim_outbox_messages(1, interval '30 seconds')
            """
        ).fetchone()
        assert first is not None
        assert first[0] == message_id
        assert first[1] == organization_id
        first_token = cast(UUID, first[2])

        admin_conn.execute(
            """
            UPDATE request_engine.outbox_messages
               SET lease_until = clock_timestamp() - interval '1 second'
             WHERE id = %s
            """,
            (message_id,),
        )

        second = worker.execute(
            """
            SELECT message_id, claim_token
            FROM request_cmd.claim_outbox_messages(1, interval '30 seconds')
            """
        ).fetchone()
        assert second is not None
        assert second[0] == message_id
        second_token = cast(UUID, second[1])
        assert second_token != first_token

        stale = worker.execute(
            "SELECT request_cmd.complete_outbox_message(%s, %s)",
            (message_id, first_token),
        ).fetchone()
        assert stale is not None
        assert stale[0] is False

        current = worker.execute(
            "SELECT request_cmd.complete_outbox_message(%s, %s)",
            (message_id, second_token),
        ).fetchone()
        assert current is not None
        assert current[0] is True
    finally:
        worker.close()
