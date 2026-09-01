"""Shared PostgreSQL world for provider-event delivery outcome proofs (F7b T1)."""

from __future__ import annotations

from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

from psycopg import Connection

from request_engine.entrypoints.worker.provider_event_router import ProviderEventRouter
from request_engine.modules.communications.adapters.worker.delivery_outcome_events import (
    DeliveryOutcomeEventHandler,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.events.provider_events import (
    PostgresProviderEventWorker,
    ProviderEventLease,
    ProviderEventReceipt,
    record_provider_event,
)
from request_engine.platform.worker.runtime import FencedWorkerRuntime, WorkerRuntimeConfig

PgConnection = Connection[Any]
PROVIDER_KEY = "webhook"
CONNECTION_KEY = "primary"
_POLICY = (
    '{"channels": ["email"], "provider_key": "webhook",'
    ' "reconcile_after_seconds": 30, "retry_after_seconds": 30}'
)


def _uuid_row(conn: PgConnection, sql: LiteralString, params: tuple[object, ...] = ()) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def new_organization(conn: PgConnection, label: str) -> UUID:
    suffix = uuid4().hex
    return _uuid_row(
        conn,
        "INSERT INTO request_engine.organizations (organization_key, display_name)"
        " VALUES (%s, %s) RETURNING id",
        (f"outcome-{label}-{suffix}", f"Outcome {label}"),
    )


def new_task(conn: PgConnection, organization_id: UUID, *, status: str = "delivering") -> UUID:
    suffix = uuid4().hex
    return _uuid_row(
        conn,
        """
        WITH party AS (
            INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
            VALUES (%s, 'person', %s) RETURNING id
        ), contact AS (
            INSERT INTO request_engine.party_contact_points (
                organization_id, party_id, channel, normalized_value, verified
            ) SELECT %s, party.id, 'email', %s, true
              FROM party RETURNING id
        )
        INSERT INTO request_engine.communication_tasks (
            organization_id, recipient_party_id, contact_point_id, purpose,
            template_key, template_version, render_context, channel_policy,
            dedupe_key, status
        ) SELECT %s, party.id, contact.id, 'appointment_confirmation',
                 'booking-confirmed', 1, '{}'::jsonb, %s::jsonb, %s, %s
          FROM party, contact
        RETURNING id
        """,
        (
            organization_id,
            f"Recipient {suffix[:8]}",
            organization_id,
            f"{suffix}@example.test",
            organization_id,
            _POLICY,
            f"outcome-task:{suffix}",
            status,
        ),
    )


def new_delivery(
    conn: PgConnection,
    organization_id: UUID,
    task_id: UUID,
    *,
    status: str = "accepted",
) -> tuple[UUID, str]:
    key = f"communication:{task_id}:attempt:1"
    delivery_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.communication_deliveries (
            organization_id, communication_task_id, attempt_no, channel,
            provider_key, provider_idempotency_key, status, result_data
        ) VALUES (%s, %s, 1, 'email', %s, %s, %s, '{}'::jsonb) RETURNING id
        """,
        (organization_id, task_id, PROVIDER_KEY, key, status),
    )
    return delivery_id, key


async def record_outcome_event(
    app_session_factory: SessionFactory,
    organization_id: UUID,
    *,
    provider_event_id: str,
    payload: dict[str, object],
) -> ProviderEventReceipt:
    async with tenant_transaction(app_session_factory, organization_id) as session:
        return await record_provider_event(
            session,
            organization_id=organization_id,
            provider_key=PROVIDER_KEY,
            connection_key=CONNECTION_KEY,
            provider_event_id=provider_event_id,
            payload=payload,
        )


def outcome_event_runtime(
    worker_session_factory: SessionFactory,
    app_session_factory: SessionFactory,
    *,
    concurrency: int = 1,
) -> FencedWorkerRuntime[ProviderEventLease]:
    store = PostgresProviderEventWorker(worker_session_factory)
    return FencedWorkerRuntime(
        store,
        ProviderEventRouter(
            {(PROVIDER_KEY, CONNECTION_KEY): DeliveryOutcomeEventHandler(app_session_factory)}
        ),
        rejecter=store.reject,
        config=WorkerRuntimeConfig(max_concurrency=concurrency, claim_batch_size=concurrency),
    )
