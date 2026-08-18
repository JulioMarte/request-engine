# pyright: reportPrivateUsage=false

import os
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection
from sqlalchemy import text

from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.events.provider_events import (
    PostgresProviderEventWorker,
    record_provider_event,
)
from request_engine.platform.outbox.postgres import append_outbox
from request_engine.platform.outbox.worker import PostgresOutboxWorker
from request_engine.platform.scheduling.postgres import PostgresScheduledActionWorker

PgConnection = Connection[Any]


@dataclass(frozen=True, slots=True)
class FamilySpec:
    name: str
    claim_sql: LiteralString


FAMILIES = (
    FamilySpec(
        name="scheduled_action",
        claim_sql="""
            SELECT action_id, claim_token
            FROM request_cmd.claim_scheduled_actions(500, interval '30 seconds')
        """,
    ),
    FamilySpec(
        name="outbox_message",
        claim_sql="""
            SELECT message_id, claim_token
            FROM request_cmd.claim_outbox_messages(500, interval '30 seconds')
        """,
    ),
    FamilySpec(
        name="provider_event",
        claim_sql="""
            SELECT provider_event_row_id, claim_token
            FROM request_cmd.claim_provider_events(500, interval '30 seconds')
        """,
    ),
)


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
        (f"release-invariant-{suffix}", f"Release invariant {suffix}"),
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
                %s, 'booking', 'test.release_invariant', 1, '{}'::jsonb, %s,
                clock_timestamp() - interval '1 minute',
                clock_timestamp() - interval '1 minute'
            )
            RETURNING id
            """,
            (organization_id, f"release-invariant:{suffix}"),
        )

    if family.name == "outbox_message":
        return _uuid_row(
            admin_conn,
            """
            INSERT INTO request_engine.outbox_messages (
                organization_id, event_type, aggregate_kind, aggregate_id,
                payload, next_attempt_at
            ) VALUES (
                %s, 'test.release_invariant.v1', 'Test', %s, '{}'::jsonb,
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
            provider_key="release-invariant-test",
            connection_key="primary",
            provider_event_id=f"event-{suffix}",
            payload={"test": "release-invariant"},
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


def _set_max_attempts(admin_conn: PgConnection, family: FamilySpec, work_id: UUID) -> None:
    if family.name == "scheduled_action":
        admin_conn.execute(
            "UPDATE request_engine.scheduled_actions SET max_attempts = 2 WHERE id = %s",
            (work_id,),
        )
    elif family.name == "outbox_message":
        admin_conn.execute(
            "UPDATE request_engine.outbox_messages SET max_attempts = 2 WHERE id = %s",
            (work_id,),
        )
    else:
        admin_conn.execute(
            "UPDATE request_engine.provider_events SET max_attempts = 2 WHERE id = %s",
            (work_id,),
        )


def _work_state(
    admin_conn: PgConnection,
    family: FamilySpec,
    work_id: UUID,
) -> tuple[object, ...] | None:
    if family.name == "scheduled_action":
        return admin_conn.execute(
            """
            SELECT status, attempt_count, max_attempts, last_error_class, claim_token
            FROM request_engine.scheduled_actions
            WHERE id = %s
            """,
            (work_id,),
        ).fetchone()
    if family.name == "outbox_message":
        return admin_conn.execute(
            """
            SELECT status, attempt_count, max_attempts, last_error_class, claim_token
            FROM request_engine.outbox_messages
            WHERE id = %s
            """,
            (work_id,),
        ).fetchone()
    return admin_conn.execute(
        """
        SELECT status, attempt_count, max_attempts, error_class, claim_token
        FROM request_engine.provider_events
        WHERE id = %s
        """,
        (work_id,),
    ).fetchone()


def _retry_current_owner(
    worker: PgConnection,
    family: FamilySpec,
    work_id: UUID,
    token: UUID,
) -> str:
    row: tuple[object, ...] | None
    if family.name == "scheduled_action":
        row = worker.execute(
            "SELECT request_cmd.retry_scheduled_action_after("
            "%s, %s, interval '0 seconds', 'release_probe')",
            (work_id, token),
        ).fetchone()
    elif family.name == "outbox_message":
        row = worker.execute(
            "SELECT request_cmd.retry_outbox_message_after("
            "%s, %s, interval '0 seconds', 'release_probe')",
            (work_id, token),
        ).fetchone()
    else:
        row = worker.execute(
            "SELECT request_cmd.retry_provider_event_after("
            "%s, %s, interval '0 seconds', 'release_probe')",
            (work_id, token),
        ).fetchone()
    assert row is not None
    return cast(str, row[0])


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.parametrize("family", FAMILIES, ids=lambda family: family.name)
async def test_i54_retry_budget_terminalizes_each_worker_family(
    family: FamilySpec,
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    work_id = await _create_work(
        family,
        admin_conn=admin_conn,
        app_session_factory=app_session_factory,
    )
    _set_max_attempts(admin_conn, family, work_id)

    worker = _worker_connection(autocommit=True)
    try:
        first_token = _claim_target(worker, family, work_id)
        assert _retry_current_owner(worker, family, work_id, first_token) == "pending"

        second_token = _claim_target(worker, family, work_id)
        assert second_token != first_token
        assert _retry_current_owner(worker, family, work_id, second_token) == "dead"
    finally:
        worker.close()

    assert _work_state(admin_conn, family, work_id) == (
        "dead",
        2,
        2,
        "release_probe",
        None,
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_i55_claim_transactions_release_row_locks_before_processing(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
    worker_session_factory: SessionFactory,
) -> None:
    scheduled_id = await _create_work(
        FAMILIES[0],
        admin_conn=admin_conn,
        app_session_factory=app_session_factory,
    )
    outbox_id = await _create_work(
        FAMILIES[1],
        admin_conn=admin_conn,
        app_session_factory=app_session_factory,
    )
    provider_id = await _create_work(
        FAMILIES[2],
        admin_conn=admin_conn,
        app_session_factory=app_session_factory,
    )

    scheduled_store = PostgresScheduledActionWorker(worker_session_factory)
    outbox_store = PostgresOutboxWorker(worker_session_factory)
    provider_store = PostgresProviderEventWorker(worker_session_factory)

    scheduled_lease = next(
        lease
        for lease in await scheduled_store.claim(limit=500, lease=timedelta(seconds=30))
        if lease.id == scheduled_id
    )
    outbox_lease = next(
        lease
        for lease in await outbox_store.claim(limit=500, lease=timedelta(seconds=30))
        if lease.id == outbox_id
    )
    provider_lease = next(
        lease
        for lease in await provider_store.claim(limit=500, lease=timedelta(seconds=30))
        if lease.id == provider_id
    )

    # Returning from each production claim() is the boundary before processors may
    # perform external work. If the claim transaction were still open, NOWAIT would
    # fail on the row lock instead of returning immediately.
    assert admin_conn.execute(
        "SELECT id FROM request_engine.scheduled_actions WHERE id = %s FOR UPDATE NOWAIT",
        (scheduled_id,),
    ).fetchone() == (scheduled_id,)
    assert admin_conn.execute(
        "SELECT id FROM request_engine.outbox_messages WHERE id = %s FOR UPDATE NOWAIT",
        (outbox_id,),
    ).fetchone() == (outbox_id,)
    assert admin_conn.execute(
        "SELECT id FROM request_engine.provider_events WHERE id = %s FOR UPDATE NOWAIT",
        (provider_id,),
    ).fetchone() == (provider_id,)

    assert await scheduled_store.complete(scheduled_lease) is True
    assert await outbox_store.complete(outbox_lease) is True
    assert await provider_store.complete(provider_lease) is True


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_i58_outbox_is_invisible_to_publisher_until_local_fact_commits(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
    worker_session_factory: SessionFactory,
) -> None:
    suffix = uuid4().hex
    organization_row = admin_conn.execute(
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"i58-{suffix}", f"I58 {suffix}"),
    ).fetchone()
    assert organization_row is not None
    organization_id = cast(UUID, organization_row[0])
    aggregate_id = uuid4()
    outbox_store = PostgresOutboxWorker(worker_session_factory)

    async with tenant_transaction(app_session_factory, organization_id) as session:
        local_fact = (
            await session.execute(
                text(
                    """
                    INSERT INTO request_engine.parties (
                        id, organization_id, party_kind, display_name
                    ) VALUES (
                        :aggregate_id, :organization_id, 'person', 'I58 local fact'
                    )
                    RETURNING id
                    """
                ),
                {"aggregate_id": aggregate_id, "organization_id": organization_id},
            )
        ).scalar_one()
        assert local_fact == aggregate_id
        await append_outbox(
            session,
            organization_id=organization_id,
            event_type="test.i58.local_fact_committed.v1",
            aggregate_kind="Party",
            aggregate_id=aggregate_id,
            payload={"party_id": str(aggregate_id)},
        )

        # Separate worker connection cannot discover an uncommitted OutboxMessage.
        before_commit = await outbox_store.claim(limit=500, lease=timedelta(seconds=30))
        assert all(
            not (
                lease.organization_id == organization_id
                and lease.aggregate_id == aggregate_id
                and lease.event_type == "test.i58.local_fact_committed.v1"
            )
            for lease in before_commit
        )

    after_commit = await outbox_store.claim(limit=500, lease=timedelta(seconds=30))
    target = next(
        lease
        for lease in after_commit
        if lease.organization_id == organization_id
        and lease.aggregate_id == aggregate_id
        and lease.event_type == "test.i58.local_fact_committed.v1"
    )
    assert admin_conn.execute(
        "SELECT id FROM request_engine.parties WHERE organization_id = %s AND id = %s",
        (organization_id, aggregate_id),
    ).fetchone() == (aggregate_id,)
    assert await outbox_store.complete(target) is True
