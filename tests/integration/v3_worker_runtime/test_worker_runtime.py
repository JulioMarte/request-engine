from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.entrypoints.worker.outbox_runtime import (
    OutboxEvent,
    OutboxPipelineProcessor,
)
from request_engine.entrypoints.worker.provider_event_router import ProviderEventRouter
from request_engine.entrypoints.worker.scheduled_router import ScheduledActionRouter
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.events.errors import ProviderEventDedupeConflict
from request_engine.platform.events.provider_events import (
    PostgresProviderEventWorker,
    ProviderEventLease,
    record_provider_event,
)
from request_engine.platform.outbox.worker import PostgresOutboxWorker
from request_engine.platform.scheduling.postgres import PostgresScheduledActionWorker
from request_engine.platform.worker.runtime import (
    FencedWorkerRuntime,
    WorkerItemState,
    WorkerRuntimeConfig,
)

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
        (f"runtime-{suffix}", f"Runtime {suffix}"),
    )


def _uuid_list() -> list[UUID]:
    return []


@dataclass
class FlakyPublisher:
    failures_remaining: int = 1
    published: list[UUID] = field(default_factory=_uuid_list)

    async def publish(self, event: OutboxEvent) -> None:
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise RuntimeError("publisher unavailable")
        self.published.append(event.id)


def _single_worker_config() -> WorkerRuntimeConfig:
    return WorkerRuntimeConfig(
        max_concurrency=1,
        claim_batch_size=1,
        lease_duration=timedelta(seconds=30),
        heartbeat_interval=timedelta(seconds=10),
        idle_sleep=timedelta(0),
        retry_base=timedelta(0),
        retry_cap=timedelta(0),
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_outbox_replays_idempotent_local_effect_after_publish_crash(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    organization_id = _organization(admin_conn)
    message_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.outbox_messages (
            organization_id, event_type, aggregate_kind, aggregate_id,
            payload, next_attempt_at
        ) VALUES (
            %s, 'test.local_then_publish.v1', 'Test', %s, '{}'::jsonb,
            '2000-01-01 00:00:00+00'
        )
        RETURNING id
        """,
        (organization_id, uuid4()),
    )
    invocations: list[UUID] = []
    applied: set[UUID] = set()

    async def local_handler(event: OutboxEvent) -> None:
        invocations.append(event.id)
        applied.add(event.id)

    publisher = FlakyPublisher()
    runtime = FencedWorkerRuntime(
        PostgresOutboxWorker(session_factory),
        OutboxPipelineProcessor(
            publisher=publisher,
            internal_handlers={"test.local_then_publish.v1": local_handler},
        ),
        config=_single_worker_config(),
    )

    first = (await runtime.run_once())[0]
    assert first.work_id == message_id
    assert first.state is WorkerItemState.RETRY
    admin_conn.execute(
        """
        UPDATE request_engine.outbox_messages
        SET next_attempt_at = '2000-01-01 00:00:00+00'
        WHERE id = %s AND status = 'pending'
        """,
        (message_id,),
    )
    second = (await runtime.run_once())[0]

    assert second.work_id == message_id
    assert second.state is WorkerItemState.COMPLETED
    assert invocations == [message_id, message_id]
    assert applied == {message_id}
    assert publisher.published == [message_id]
    assert admin_conn.execute(
        "SELECT status, attempt_count FROM request_engine.outbox_messages WHERE id = %s",
        (message_id,),
    ).fetchone() == ("delivered", 2)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_provider_event_identity_dedupes_canonical_payload_and_rejects_mutation(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    organization_id = _organization(admin_conn)
    async with tenant_transaction(session_factory, organization_id) as session:
        first = await record_provider_event(
            session,
            organization_id=organization_id,
            provider_key="fake",
            connection_key="primary",
            provider_event_id="event-1",
            payload={"a": 1, "b": 2},
        )
    async with tenant_transaction(session_factory, organization_id) as session:
        replay = await record_provider_event(
            session,
            organization_id=organization_id,
            provider_key="fake",
            connection_key="primary",
            provider_event_id="event-1",
            payload={"b": 2, "a": 1},
        )

    assert replay.id == first.id
    assert replay.replay is True
    with pytest.raises(ProviderEventDedupeConflict):
        async with tenant_transaction(session_factory, organization_id) as session:
            await record_provider_event(
                session,
                organization_id=organization_id,
                provider_key="fake",
                connection_key="primary",
                provider_event_id="event-1",
                payload={"a": 999, "b": 2},
            )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_provider_event_router_runs_under_generic_fenced_runtime(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    organization_id = _organization(admin_conn)
    async with tenant_transaction(session_factory, organization_id) as session:
        receipt = await record_provider_event(
            session,
            organization_id=organization_id,
            provider_key="fake",
            connection_key="primary",
            provider_event_id=f"event-{uuid4().hex}",
            payload={"status": "delivered"},
        )
    admin_conn.execute(
        "UPDATE request_engine.provider_events SET next_attempt_at = '2000-01-01' WHERE id = %s",
        (receipt.id,),
    )
    handled: list[UUID] = []

    async def handle(lease: ProviderEventLease) -> None:
        handled.append(lease.id)

    runtime = FencedWorkerRuntime(
        PostgresProviderEventWorker(session_factory),
        ProviderEventRouter({("fake", "primary"): handle}),
        config=_single_worker_config(),
    )
    outcome = (await runtime.run_once())[0]

    assert outcome.work_id == receipt.id
    assert outcome.state is WorkerItemState.COMPLETED
    assert handled == [receipt.id]
    assert admin_conn.execute(
        "SELECT status, processed_at IS NOT NULL FROM request_engine.provider_events WHERE id = %s",
        (receipt.id,),
    ).fetchone() == ("processed", True)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_unregistered_scheduled_action_is_dead_lettered_not_retried(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    organization_id = _organization(admin_conn)
    action_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.scheduled_actions (
            organization_id, owner_module, action_type, payload,
            dedupe_key, execute_at, next_attempt_at
        ) VALUES (
            %s, 'unknown', 'unknown.action', '{}'::jsonb, %s,
            '2000-01-01 00:00:00+00', '2000-01-01 00:00:00+00'
        )
        RETURNING id
        """,
        (organization_id, f"unknown:{uuid4().hex}"),
    )
    runtime = FencedWorkerRuntime(
        PostgresScheduledActionWorker(session_factory),
        ScheduledActionRouter({}),
        config=_single_worker_config(),
    )
    outcome = (await runtime.run_once())[0]

    assert outcome.work_id == action_id
    assert outcome.state is WorkerItemState.DEAD
    assert admin_conn.execute(
        """
        SELECT status, last_error_class
        FROM request_engine.scheduled_actions
        WHERE id = %s
        """,
        (action_id,),
    ).fetchone() == ("dead", "unsupported_scheduled_action")
