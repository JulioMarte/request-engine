from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection

PgConnection = Connection[Any]


def _organization(conn: PgConnection, label: str) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"scheduler-{label}-{uuid4().hex}", f"Scheduler {label}"),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _action(conn: PgConnection, organization_id: UUID, label: str) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.scheduled_actions (
            organization_id, owner_module, action_type, payload, dedupe_key,
            execute_at, next_attempt_at
        ) VALUES (
            %s, 'communications', 'test_action', '{}'::jsonb, %s,
            clock_timestamp() - interval '1 minute',
            clock_timestamp() - interval '1 minute'
        )
        RETURNING id
        """,
        (organization_id, f"{label}-{uuid4().hex}"),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


@pytest.mark.postgres
@pytest.mark.concurrency
def test_scheduled_action_claim_is_tenant_fair(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    noisy = _organization(admin_conn, "noisy")
    quiet_a = _organization(admin_conn, "quiet-a")
    quiet_b = _organization(admin_conn, "quiet-b")
    for index in range(6):
        _action(admin_conn, noisy, f"noisy-{index}")
    _action(admin_conn, quiet_a, "quiet-a")
    _action(admin_conn, quiet_b, "quiet-b")

    worker: PgConnection = psycopg.connect(pg_conninfo, autocommit=True)
    try:
        worker.execute("SET ROLE request_engine_worker")
        rows = worker.execute(
            """
            SELECT action_id, organization_id
            FROM request_cmd.claim_scheduled_actions(3, interval '30 seconds')
            """
        ).fetchall()
        assert len(rows) == 3
        assert {cast(UUID, row[1]) for row in rows} == {noisy, quiet_a, quiet_b}
    finally:
        worker.close()


@pytest.mark.postgres
@pytest.mark.concurrency
def test_scheduled_action_renewal_is_fenced(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    organization_id = _organization(admin_conn, "renew")
    action_id = _action(admin_conn, organization_id, "renew")
    worker: PgConnection = psycopg.connect(pg_conninfo, autocommit=True)
    try:
        worker.execute("SET ROLE request_engine_worker")
        first = worker.execute(
            """
            SELECT action_id, claim_token, lease_until
            FROM request_cmd.claim_scheduled_actions(1, interval '30 seconds')
            """
        ).fetchone()
        assert first is not None
        assert first[0] == action_id
        first_token = cast(UUID, first[1])
        first_until = first[2]

        renewed = worker.execute(
            "SELECT request_cmd.renew_scheduled_action_lease(%s, %s, interval '90 seconds')",
            (action_id, first_token),
        ).fetchone()
        assert renewed is not None
        assert renewed[0] is not None
        assert renewed[0] > first_until

        wrong = worker.execute(
            "SELECT request_cmd.renew_scheduled_action_lease(%s, %s, interval '90 seconds')",
            (action_id, uuid4()),
        ).fetchone()
        assert wrong == (None,)

        admin_conn.execute(
            """
            UPDATE request_engine.scheduled_actions
               SET lease_until = clock_timestamp() - interval '1 second'
             WHERE id = %s
            """,
            (action_id,),
        )
        expired = worker.execute(
            "SELECT request_cmd.renew_scheduled_action_lease(%s, %s, interval '90 seconds')",
            (action_id, first_token),
        ).fetchone()
        assert expired == (None,)

        second = worker.execute(
            """
            SELECT action_id, claim_token
            FROM request_cmd.claim_scheduled_actions(1, interval '30 seconds')
            """
        ).fetchone()
        assert second is not None
        second_token = cast(UUID, second[1])
        assert second_token != first_token

        stale = worker.execute(
            "SELECT request_cmd.complete_scheduled_action(%s, %s)",
            (action_id, first_token),
        ).fetchone()
        assert stale == (False,)
        current = worker.execute(
            "SELECT request_cmd.complete_scheduled_action(%s, %s)",
            (action_id, second_token),
        ).fetchone()
        assert current == (True,)
    finally:
        worker.close()
