import os
import queue
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection

from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.events.provider_events import record_provider_event

PgConnection = Connection[Any]


@dataclass(frozen=True, slots=True)
class FamilySpec:
    name: str
    claim_sql: LiteralString
    expire_sql: LiteralString
    state_sql: LiteralString
    terminal_status: str


FAMILIES = (
    FamilySpec(
        name="scheduled_action",
        claim_sql="""
            SELECT action_id, claim_token
            FROM request_cmd.claim_scheduled_actions(500, interval '30 seconds')
        """,
        expire_sql="""
            UPDATE request_engine.scheduled_actions
            SET lease_until = clock_timestamp() - interval '1 second'
            WHERE id = %s
        """,
        state_sql="""
            SELECT status, claim_token, attempt_count, lease_until > clock_timestamp()
            FROM request_engine.scheduled_actions
            WHERE id = %s
        """,
        terminal_status="completed",
    ),
    FamilySpec(
        name="outbox_message",
        claim_sql="""
            SELECT message_id, claim_token
            FROM request_cmd.claim_outbox_messages(500, interval '30 seconds')
        """,
        expire_sql="""
            UPDATE request_engine.outbox_messages
            SET lease_until = clock_timestamp() - interval '1 second'
            WHERE id = %s
        """,
        state_sql="""
            SELECT status, claim_token, attempt_count, lease_until > clock_timestamp()
            FROM request_engine.outbox_messages
            WHERE id = %s
        """,
        terminal_status="delivered",
    ),
    FamilySpec(
        name="provider_event",
        claim_sql="""
            SELECT provider_event_row_id, claim_token
            FROM request_cmd.claim_provider_events(500, interval '30 seconds')
        """,
        expire_sql="""
            UPDATE request_engine.provider_events
            SET lease_until = clock_timestamp() - interval '1 second'
            WHERE id = %s
        """,
        state_sql="""
            SELECT status, claim_token, attempt_count, lease_until > clock_timestamp()
            FROM request_engine.provider_events
            WHERE id = %s
        """,
        terminal_status="processed",
    ),
)

OUTBOX = FAMILIES[1]


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


def _worker_connection(*, autocommit: bool) -> PgConnection:
    connection: PgConnection = psycopg.connect(_conninfo(), autocommit=autocommit)
    connection.execute("SET ROLE request_engine_worker")
    return connection


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...],
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _organization(admin_conn: PgConnection) -> UUID:
    suffix = uuid4().hex
    return _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"fencing-{suffix}", f"Fencing {suffix}"),
    )


async def _create_work(
    family: FamilySpec,
    *,
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> UUID:
    organization_id = _organization(admin_conn)
    suffix = uuid4().hex

    if family.name == "scheduled_action":
        return _uuid_row(
            admin_conn,
            """
            INSERT INTO request_engine.scheduled_actions (
                organization_id, owner_module, action_type, action_version,
                payload, dedupe_key, execute_at, next_attempt_at
            ) VALUES (
                %s, 'booking', 'test.fencing', 1, '{}'::jsonb, %s,
                clock_timestamp() - interval '1 minute',
                clock_timestamp() - interval '1 minute'
            )
            RETURNING id
            """,
            (organization_id, f"fencing:{suffix}"),
        )

    if family.name == "outbox_message":
        return _uuid_row(
            admin_conn,
            """
            INSERT INTO request_engine.outbox_messages (
                organization_id, event_type, aggregate_kind, aggregate_id,
                payload, next_attempt_at
            ) VALUES (
                %s, 'test.fencing.v1', 'Test', %s, '{}'::jsonb,
                clock_timestamp() - interval '1 minute'
            )
            RETURNING id
            """,
            (organization_id, uuid4()),
        )

    async with tenant_transaction(app_session_factory, organization_id) as session:
        receipt = await record_provider_event(
            session,
            organization_id=organization_id,
            provider_key="fencing-test",
            connection_key="primary",
            provider_event_id=f"event-{suffix}",
            payload={"test": "fencing"},
        )
    admin_conn.execute(
        """
        UPDATE request_engine.provider_events
        SET next_attempt_at = clock_timestamp() - interval '1 minute'
        WHERE id = %s
        """,
        (receipt.id,),
    )
    return receipt.id


def _claim_target(connection: PgConnection, family: FamilySpec, work_id: UUID) -> UUID:
    rows = connection.execute(family.claim_sql).fetchall()
    row = next((candidate for candidate in rows if candidate[0] == work_id), None)
    assert row is not None
    return cast(UUID, row[1])


def _assert_target_not_claimed(
    connection: PgConnection,
    family: FamilySpec,
    work_id: UUID,
) -> None:
    rows = connection.execute(family.claim_sql).fetchall()
    assert all(candidate[0] != work_id for candidate in rows)


def _assert_stale_transitions_are_fenced(
    connection: PgConnection,
    family: FamilySpec,
    work_id: UUID,
    stale_token: UUID,
) -> None:
    if family.name == "scheduled_action":
        assert connection.execute(
            "SELECT request_cmd.renew_scheduled_action_lease(%s, %s, interval '30 seconds')",
            (work_id, stale_token),
        ).fetchone() == (False,)
        assert connection.execute(
            "SELECT request_cmd.complete_scheduled_action(%s, %s)",
            (work_id, stale_token),
        ).fetchone() == (False,)
        assert connection.execute(
            "SELECT request_cmd.retry_scheduled_action_after(%s, %s, interval '1 second', 'stale')",
            (work_id, stale_token),
        ).fetchone() == ("stale",)
        assert connection.execute(
            "SELECT request_cmd.dead_letter_scheduled_action(%s, %s, 'stale')",
            (work_id, stale_token),
        ).fetchone() == (False,)
        return

    if family.name == "outbox_message":
        assert connection.execute(
            "SELECT request_cmd.renew_outbox_message_lease(%s, %s, interval '30 seconds')",
            (work_id, stale_token),
        ).fetchone() == (False,)
        assert connection.execute(
            "SELECT request_cmd.complete_outbox_message(%s, %s)",
            (work_id, stale_token),
        ).fetchone() == (False,)
        assert connection.execute(
            "SELECT request_cmd.retry_outbox_message_after(%s, %s, interval '1 second', 'stale')",
            (work_id, stale_token),
        ).fetchone() == ("stale",)
        assert connection.execute(
            "SELECT request_cmd.dead_letter_outbox_message(%s, %s, 'stale')",
            (work_id, stale_token),
        ).fetchone() == (False,)
        return

    assert connection.execute(
        "SELECT request_cmd.renew_provider_event_lease(%s, %s, interval '30 seconds')",
        (work_id, stale_token),
    ).fetchone() == (False,)
    assert connection.execute(
        "SELECT request_cmd.complete_provider_event(%s, %s)",
        (work_id, stale_token),
    ).fetchone() == (False,)
    assert connection.execute(
        "SELECT request_cmd.retry_provider_event_after(%s, %s, interval '1 second', 'stale')",
        (work_id, stale_token),
    ).fetchone() == ("stale",)
    assert connection.execute(
        "SELECT request_cmd.dead_letter_provider_event(%s, %s, 'stale')",
        (work_id, stale_token),
    ).fetchone() == (False,)
    assert connection.execute(
        "SELECT request_cmd.reject_provider_event(%s, %s, 'stale')",
        (work_id, stale_token),
    ).fetchone() == (False,)


def _complete_current_owner(
    connection: PgConnection,
    family: FamilySpec,
    work_id: UUID,
    token: UUID,
) -> None:
    query: LiteralString
    if family.name == "scheduled_action":
        query = "SELECT request_cmd.complete_scheduled_action(%s, %s)"
    elif family.name == "outbox_message":
        query = "SELECT request_cmd.complete_outbox_message(%s, %s)"
    else:
        query = "SELECT request_cmd.complete_provider_event(%s, %s)"
    assert connection.execute(query, (work_id, token)).fetchone() == (True,)


def _wait_until_lock_blocked(admin_conn: PgConnection, backend_pid: int) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        row = admin_conn.execute(
            "SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s",
            (backend_pid,),
        ).fetchone()
        if row is not None and row[0] == "Lock":
            return
        time.sleep(0.01)
    raise AssertionError(f"backend {backend_pid} never blocked on the expected row lock")


def _complete_outbox_in_thread(
    message_id: UUID,
    stale_token: UUID,
    backend_queue: queue.Queue[int],
) -> bool:
    worker = _worker_connection(autocommit=True)
    try:
        backend_queue.put(worker.info.backend_pid)
        row = worker.execute(
            "SELECT request_cmd.complete_outbox_message(%s, %s)",
            (message_id, stale_token),
        ).fetchone()
        assert row is not None
        return cast(bool, row[0])
    finally:
        worker.close()


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
@pytest.mark.parametrize("family", FAMILIES, ids=lambda family: family.name)
async def test_r12_claim_vs_claim_has_one_current_owner(
    family: FamilySpec,
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    work_id = await _create_work(
        family,
        admin_conn=admin_conn,
        app_session_factory=app_session_factory,
    )
    first = _worker_connection(autocommit=False)
    second = _worker_connection(autocommit=True)
    try:
        first_token = _claim_target(first, family, work_id)

        # The first claim transaction deliberately remains open. The row is locked,
        # so the independent worker must SKIP LOCKED rather than claim the same work.
        _assert_target_not_claimed(second, family, work_id)
        first.commit()

        state = admin_conn.execute(family.state_sql, (work_id,)).fetchone()
        assert state == ("leased", first_token, 1, True)
    finally:
        first.rollback()
        first.close()
        second.close()


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
@pytest.mark.parametrize("family", FAMILIES, ids=lambda family: family.name)
async def test_r13_r14_reclaim_fences_every_stale_transition_and_late_renewal(
    family: FamilySpec,
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    work_id = await _create_work(
        family,
        admin_conn=admin_conn,
        app_session_factory=app_session_factory,
    )
    worker = _worker_connection(autocommit=True)
    try:
        first_token = _claim_target(worker, family, work_id)
        admin_conn.execute(family.expire_sql, (work_id,))

        second_token = _claim_target(worker, family, work_id)
        assert second_token != first_token

        _assert_stale_transitions_are_fenced(worker, family, work_id, first_token)
        assert admin_conn.execute(family.state_sql, (work_id,)).fetchone() == (
            "leased",
            second_token,
            2,
            True,
        )

        _complete_current_owner(worker, family, work_id, second_token)
        terminal = admin_conn.execute(family.state_sql, (work_id,)).fetchone()
        assert terminal is not None
        assert terminal[0] == family.terminal_status
        assert terminal[1] is None
        assert terminal[2] == 2
        assert terminal[3] is None
    finally:
        worker.close()


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_r16_outbox_completion_wins_row_lock_and_prevents_reclaim(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    message_id = await _create_work(
        OUTBOX,
        admin_conn=admin_conn,
        app_session_factory=app_session_factory,
    )
    claimant = _worker_connection(autocommit=True)
    completer = _worker_connection(autocommit=False)
    competitor = _worker_connection(autocommit=True)
    try:
        token = _claim_target(claimant, OUTBOX, message_id)
        assert completer.execute(
            "SELECT request_cmd.complete_outbox_message(%s, %s)",
            (message_id, token),
        ).fetchone() == (True,)

        # Completion owns the row lock until commit. A concurrent claimant must skip
        # the row and cannot create a second owner behind a successful finalization.
        _assert_target_not_claimed(competitor, OUTBOX, message_id)
        completer.commit()
    finally:
        completer.rollback()
        claimant.close()
        completer.close()
        competitor.close()

    assert admin_conn.execute(OUTBOX.state_sql, (message_id,)).fetchone() == (
        "delivered",
        None,
        1,
        None,
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_r16_outbox_reclaim_wins_row_lock_and_fences_stale_completion(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    message_id = await _create_work(
        OUTBOX,
        admin_conn=admin_conn,
        app_session_factory=app_session_factory,
    )
    first_owner = _worker_connection(autocommit=True)
    reclaimer = _worker_connection(autocommit=False)
    try:
        stale_token = _claim_target(first_owner, OUTBOX, message_id)
        admin_conn.execute(OUTBOX.expire_sql, (message_id,))
        current_token = _claim_target(reclaimer, OUTBOX, message_id)
        assert current_token != stale_token

        backend_queue: queue.Queue[int] = queue.Queue()
        with ThreadPoolExecutor(max_workers=1) as executor:
            stale_completion = executor.submit(
                _complete_outbox_in_thread,
                message_id,
                stale_token,
                backend_queue,
            )
            _wait_until_lock_blocked(admin_conn, backend_queue.get(timeout=2))
            reclaimer.commit()
            assert stale_completion.result(timeout=5) is False

        assert admin_conn.execute(OUTBOX.state_sql, (message_id,)).fetchone() == (
            "leased",
            current_token,
            2,
            True,
        )
        _complete_current_owner(first_owner, OUTBOX, message_id, current_token)
    finally:
        reclaimer.rollback()
        first_owner.close()
        reclaimer.close()

    assert admin_conn.execute(OUTBOX.state_sql, (message_id,)).fetchone() == (
        "delivered",
        None,
        2,
        None,
    )
