from datetime import timedelta
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection
from sqlalchemy import text

from request_engine.bootstrap.worker import WorkerProcessConfig, build_worker_process
from request_engine.entrypoints.worker.outbox_runtime import OutboxEvent
from request_engine.modules.booking.adapters.db.lifecycle_scheduling import (
    NO_SHOW_ACTION_TYPE,
    NO_SHOW_ACTION_VERSION,
)
from request_engine.modules.booking.adapters.worker.no_show import NoShowScheduledHandler
from request_engine.modules.queue.adapters.worker.slot_offer_expiry import (
    SlotOfferExpiryScheduledHandler,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.events.provider_events import ProviderEventLease, record_provider_event
from request_engine.platform.worker.runtime import RejectedWorkError, WorkerItemState, WorkerRuntimeConfig

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
        (f"worker-assembly-{suffix}", f"Worker Assembly {suffix}"),
    )


def _single_worker_config() -> WorkerRuntimeConfig:
    return WorkerRuntimeConfig(
        max_concurrency=1,
        claim_batch_size=1,
        lease_duration=timedelta(seconds=30),
        heartbeat_interval=timedelta(seconds=10),
        idle_sleep=timedelta(milliseconds=1),
        retry_base=timedelta(0),
        retry_cap=timedelta(0),
    )


class _ScheduledHandler:
    async def handle(self, lease: object) -> None:
        del lease


class _Publisher:
    def __init__(self) -> None:
        self.published: list[UUID] = []

    async def publish(self, event: OutboxEvent) -> None:
        self.published.append(event.id)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_production_worker_assembly_enforces_runtime_role_split(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
    worker_session_factory: SessionFactory,
) -> None:
    async with worker_session_factory() as worker_session:
        worker_roles = (
            await worker_session.execute(
                text(
                    """
                    SELECT
                        pg_has_role(current_user, 'request_engine_worker', 'member'),
                        pg_has_role(current_user, 'request_engine_app', 'member')
                    """
                )
            )
        ).one()
    async with app_session_factory() as app_session:
        app_roles = (
            await app_session.execute(
                text(
                    """
                    SELECT
                        pg_has_role(current_user, 'request_engine_app', 'member'),
                        pg_has_role(current_user, 'request_engine_worker', 'member')
                    """
                )
            )
        ).one()

    assert worker_roles == (True, False)
    assert app_roles == (True, False)

    organization_id = _organization(admin_conn)
    action_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.scheduled_actions (
            organization_id,
            owner_module,
            action_type,
            action_version,
            payload,
            dedupe_key,
            execute_at,
            next_attempt_at
        ) VALUES (
            %s,
            'booking',
            %s,
            %s,
            '{}'::jsonb,
            %s,
            '2000-01-01 00:00:00+00',
            '2000-01-01 00:00:00+00'
        )
        RETURNING id
        """,
        (
            organization_id,
            NO_SHOW_ACTION_TYPE,
            NO_SHOW_ACTION_VERSION,
            f"worker-assembly-action:{uuid4().hex}",
        ),
    )
    message_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.outbox_messages (
            organization_id,
            event_type,
            payload,
            next_attempt_at
        ) VALUES (
            %s,
            'test.worker_assembly.v1',
            '{}'::jsonb,
            '2000-01-01 00:00:00+00'
        )
        RETURNING id
        """,
        (organization_id,),
    )

    async with tenant_transaction(app_session_factory, organization_id) as session:
        provider_receipt = await record_provider_event(
            session,
            organization_id=organization_id,
            provider_key="fake",
            connection_key="primary",
            provider_event_id=f"worker-assembly-{uuid4().hex}",
            payload={"kind": "unsupported"},
        )
    admin_conn.execute(
        """
        UPDATE request_engine.provider_events
        SET next_attempt_at = '2000-01-01 00:00:00+00'
        WHERE id = %s
        """,
        (provider_receipt.id,),
    )

    domain_factories_seen: list[SessionFactory] = []

    def no_show_factory(factory: SessionFactory) -> NoShowScheduledHandler:
        domain_factories_seen.append(factory)
        return cast(NoShowScheduledHandler, _ScheduledHandler())

    def slot_offer_factory(factory: SessionFactory) -> SlotOfferExpiryScheduledHandler:
        domain_factories_seen.append(factory)
        return cast(SlotOfferExpiryScheduledHandler, _ScheduledHandler())

    async def reject_provider_event(lease: ProviderEventLease) -> None:
        del lease
        raise RejectedWorkError("unsupported_provider_payload")

    publisher = _Publisher()
    process = build_worker_process(
        worker_session_factory=worker_session_factory,
        domain_session_factory=app_session_factory,
        no_show_factory=no_show_factory,
        slot_offer_expiry_factory=slot_offer_factory,
        communication_providers={},
        outbox_publisher=publisher,
        outbox_internal_handlers={},
        provider_event_handlers={("fake", "primary"): reject_provider_event},
        config=WorkerProcessConfig(
            scheduled_actions=_single_worker_config(),
            outbox_messages=_single_worker_config(),
            provider_events=_single_worker_config(),
        ),
    )

    report = await process.run_once()

    assert domain_factories_seen == [app_session_factory, app_session_factory]
    assert report.scheduled_actions[0].work_id == action_id
    assert report.scheduled_actions[0].state is WorkerItemState.COMPLETED
    assert report.outbox_messages[0].work_id == message_id
    assert report.outbox_messages[0].state is WorkerItemState.COMPLETED
    assert report.provider_events[0].work_id == provider_receipt.id
    assert report.provider_events[0].state is WorkerItemState.REJECTED
    assert publisher.published == [message_id]

    assert admin_conn.execute(
        "SELECT status FROM request_engine.scheduled_actions WHERE id = %s",
        (action_id,),
    ).fetchone() == ("completed",)
    assert admin_conn.execute(
        "SELECT status FROM request_engine.outbox_messages WHERE id = %s",
        (message_id,),
    ).fetchone() == ("delivered",)
    assert admin_conn.execute(
        """
        SELECT status, last_error_class
        FROM request_engine.provider_events
        WHERE id = %s
        """,
        (provider_receipt.id,),
    ).fetchone() == ("rejected", "unsupported_provider_payload")
