import os
import queue
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection

PgConnection = Connection[Any]


def _conninfo() -> str:
    return " ".join(
        (
            f"host={os.environ.get('PGHOST', '127.0.0.1')}",
            f"port={os.environ.get('PGPORT', '5432')}",
            f"dbname={os.environ.get('PGDATABASE', 'request_engine_v3')}",
            f"user={os.environ.get('PGUSER', 'request_engine')}",
            f"password={os.environ.get('PGPASSWORD', 'request_engine')}",
        )
    )


def _seed(admin_conn: PgConnection, label: str) -> tuple[UUID, UUID]:
    suffix = uuid4().hex
    organization = admin_conn.execute(
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"cancel-race-{label}-{suffix}", f"Cancel race {label}"),
    ).fetchone()
    assert organization is not None
    organization_id = cast(UUID, organization[0])
    action = admin_conn.execute(
        """
        INSERT INTO request_engine.scheduled_actions (
            organization_id, owner_module, action_type, action_version,
            payload, dedupe_key, execute_at, next_attempt_at
        ) VALUES (
            %s, 'booking', 'test.cancel_race', 1, '{}'::jsonb, %s,
            clock_timestamp() - interval '1 minute',
            clock_timestamp() - interval '1 minute'
        )
        RETURNING id
        """,
        (organization_id, f"cancel-race:{suffix}"),
    ).fetchone()
    assert action is not None
    return organization_id, cast(UUID, action[0])


def _app_connection(organization_id: UUID, *, autocommit: bool) -> PgConnection:
    connection: PgConnection = psycopg.connect(_conninfo(), autocommit=autocommit)
    connection.execute("SET ROLE request_engine_app")
    connection.execute(
        "SELECT set_config('request_engine.organization_id', %s, false)",
        (str(organization_id),),
    )
    return connection


def _worker_connection(*, autocommit: bool) -> PgConnection:
    connection: PgConnection = psycopg.connect(_conninfo(), autocommit=autocommit)
    connection.execute("SET ROLE request_engine_worker")
    return connection


def _wait_until_lock_blocked(admin_conn: PgConnection, backend_pid: int) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        row = admin_conn.execute(
            """
            SELECT wait_event_type
            FROM pg_stat_activity
            WHERE pid = %s
            """,
            (backend_pid,),
        ).fetchone()
        if row is not None and row[0] == "Lock":
            return
        time.sleep(0.01)
    raise AssertionError(f"backend {backend_pid} never blocked on the expected row lock")


def _cancel_in_thread(
    organization_id: UUID,
    action_id: UUID,
    backend_queue: queue.Queue[int],
) -> str:
    connection = _app_connection(organization_id, autocommit=True)
    try:
        backend_queue.put(connection.info.backend_pid)
        row = connection.execute(
            "SELECT request_cmd.cancel_scheduled_action(%s, %s)",
            (organization_id, action_id),
        ).fetchone()
        assert row is not None
        return cast(str, row[0])
    finally:
        connection.close()


def _claim_in_thread(action_id: UUID) -> UUID | None:
    connection = _worker_connection(autocommit=True)
    try:
        rows = connection.execute(
            """
            SELECT action_id, claim_token
            FROM request_cmd.claim_scheduled_actions(500, interval '30 seconds')
            """
        ).fetchall()
        match = next((row for row in rows if row[0] == action_id), None)
        return None if match is None else cast(UUID, match[1])
    finally:
        connection.close()


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
def test_r15_cancel_wins_row_lock_and_claim_cannot_resurrect_action(
    admin_conn: PgConnection,
) -> None:
    organization_id, action_id = _seed(admin_conn, "cancel-wins")
    app = _app_connection(organization_id, autocommit=False)
    try:
        cancelled = app.execute(
            "SELECT request_cmd.cancel_scheduled_action(%s, %s)",
            (organization_id, action_id),
        ).fetchone()
        assert cancelled == ("cancelled",)

        # The uncommitted cancellation owns the row lock. Worker discovery uses SKIP LOCKED,
        # so a concurrent claimer must skip this row rather than wait and resurrect it later.
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_claim_in_thread, action_id)
            assert future.result(timeout=5) is None
        app.commit()
    finally:
        app.close()

    assert admin_conn.execute(
        """
        SELECT status, claim_token, lease_until, attempt_count
        FROM request_engine.scheduled_actions
        WHERE id = %s
        """,
        (action_id,),
    ).fetchone() == ("cancelled", None, None, 0)


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
def test_r15_claim_wins_row_lock_then_cancel_fences_claim_token(
    admin_conn: PgConnection,
) -> None:
    organization_id, action_id = _seed(admin_conn, "claim-wins")
    worker = _worker_connection(autocommit=False)
    try:
        rows = worker.execute(
            """
            SELECT action_id, claim_token
            FROM request_cmd.claim_scheduled_actions(500, interval '30 seconds')
            """
        ).fetchall()
        target = next(row for row in rows if row[0] == action_id)
        token = cast(UUID, target[1])

        backend_queue: queue.Queue[int] = queue.Queue()
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                _cancel_in_thread,
                organization_id,
                action_id,
                backend_queue,
            )
            _wait_until_lock_blocked(admin_conn, backend_queue.get(timeout=2))
            worker.commit()
            assert future.result(timeout=5) == "cancelled"
    finally:
        worker.close()

    stale_worker = _worker_connection(autocommit=True)
    try:
        assert stale_worker.execute(
            "SELECT request_cmd.complete_scheduled_action(%s, %s)",
            (action_id, token),
        ).fetchone() == (False,)
        assert stale_worker.execute(
            "SELECT request_cmd.lock_scheduled_action_claim(%s, %s)",
            (action_id, token),
        ).fetchone() == (False,)
    finally:
        stale_worker.close()

    assert admin_conn.execute(
        """
        SELECT status, claim_token, lease_until, attempt_count
        FROM request_engine.scheduled_actions
        WHERE id = %s
        """,
        (action_id,),
    ).fetchone() == ("cancelled", None, None, 1)
