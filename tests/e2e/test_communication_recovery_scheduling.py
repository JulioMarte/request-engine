from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

import pytest

from request_engine.modules.communications.adapters.db.delivery_store import (
    DeliveryWorkKind,
    finalize_provider_result,
    prepare_dispatch,
)
from request_engine.modules.communications.contracts.delivery import (
    ProviderDeliveryResult,
    ProviderDeliveryStatus,
)
from request_engine.platform.db.session import (
    SessionFactory,
    create_postgres_engine,
    create_session_factory,
    tenant_transaction,
)

from . import operational_support as support

pytestmark = [pytest.mark.postgres, pytest.mark.e2e]


@asynccontextmanager
async def _domain_factory(
    credentials: support.RuntimeCredentialsLike,
) -> AsyncGenerator[SessionFactory]:
    domain_database_url = getattr(credentials, "domain_database_url", None)
    assert domain_database_url is not None, "communications proofs require app credentials"
    engine = create_postgres_engine(domain_database_url)
    try:
        yield create_session_factory(engine)
    finally:
        await engine.dispose()


def _new_task(conn: support.PgConnection, organization_id: UUID) -> UUID:
    party_id = support.new_party(conn, organization_id, f"Recipient {uuid4().hex[:8]}")
    contact_point_id = support.new_contact_point(conn, organization_id, party_id, "recovery")
    policy = {
        "channels": ["email"],
        "provider_key": "provider-a",
        "reconcile_after_seconds": 30,
        "retry_after_seconds": 30,
    }
    row = conn.execute(
        """
        INSERT INTO request_engine.communication_tasks (
            organization_id, recipient_party_id, contact_point_id,
            purpose, template_key, template_version, render_context,
            channel_policy, dedupe_key, status
        ) VALUES (
            %s, %s, %s, 'confirmation', 'booking-confirmed', 1,
            '{}'::jsonb, %s::jsonb, %s, 'pending'
        )
        RETURNING id
        """,
        (
            organization_id,
            party_id,
            contact_point_id,
            json.dumps(policy),
            f"recovery-task:{uuid4().hex}",
        ),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _insert_fake_action(
    conn: support.PgConnection,
    organization_id: UUID,
    *,
    action_type: str,
    action_version: int,
    subject_kind: str,
    subject_id: UUID,
    payload: dict[str, str],
    exhausted: bool,
) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.scheduled_actions (
            organization_id, owner_module, action_type, action_version,
            subject_kind, subject_id, payload, dedupe_key,
            execute_at, next_attempt_at, attempt_count, max_attempts
        ) VALUES (
            %s, 'communications', %s, %s,
            %s, %s, %s::jsonb, %s,
            clock_timestamp() + interval '1 hour',
            clock_timestamp() + interval '1 hour',
            CASE WHEN %s THEN 8 ELSE 0 END,
            8
        )
        RETURNING id
        """,
        (
            organization_id,
            action_type,
            action_version,
            subject_kind,
            subject_id,
            json.dumps(payload),
            f"recovery-fake:{uuid4().hex}",
            exhausted,
        ),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


@pytest.mark.asyncio
async def test_exhausted_and_malformed_future_dispatches_do_not_suppress_real_retry_work(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    organization_id = support.new_org(e2e_admin_conn, "dispatch-recovery-semantics")
    task_id = _new_task(e2e_admin_conn, organization_id)

    async with _domain_factory(worker_runtime_credentials) as session_factory:
        async with tenant_transaction(session_factory, organization_id) as session:
            first = await prepare_dispatch(
                session,
                organization_id=organization_id,
                communication_task_id=task_id,
            )
        assert first.kind is DeliveryWorkKind.SEND
        assert first.delivery_id is not None

        async with tenant_transaction(session_factory, organization_id) as session:
            await finalize_provider_result(
                session,
                organization_id=organization_id,
                delivery_id=first.delivery_id,
                result=ProviderDeliveryResult(
                    status=ProviderDeliveryStatus.FAILED,
                    retryable=True,
                    result_data={"source": "recovery-test"},
                ),
            )

        retry_row = e2e_admin_conn.execute(
            """
            SELECT id
            FROM request_engine.scheduled_actions
            WHERE organization_id = %s
              AND owner_module = 'communications'
              AND action_type = 'dispatch_task'
              AND subject_kind = 'CommunicationTask'
              AND subject_id = %s
              AND status = 'pending'
            ORDER BY created_at, id
            LIMIT 1
            """,
            (organization_id, task_id),
        ).fetchone()
        assert retry_row is not None
        exhausted_retry_id = cast(UUID, retry_row[0])
        e2e_admin_conn.execute(
            """
            UPDATE request_engine.scheduled_actions
            SET attempt_count = max_attempts
            WHERE id = %s
            """,
            (exhausted_retry_id,),
        )
        malformed_retry_id = _insert_fake_action(
            e2e_admin_conn,
            organization_id,
            action_type="dispatch_task",
            action_version=999,
            subject_kind="CommunicationTask",
            subject_id=task_id,
            payload={"communication_task_id": str(uuid4())},
            exhausted=False,
        )

        async with tenant_transaction(session_factory, organization_id) as session:
            second = await prepare_dispatch(
                session,
                organization_id=organization_id,
                communication_task_id=task_id,
            )

    assert second.kind is DeliveryWorkKind.SEND
    assert second.delivery_id is not None
    assert second.delivery_id != first.delivery_id
    assert e2e_admin_conn.execute(
        """
        SELECT array_agg(attempt_no ORDER BY attempt_no)
        FROM request_engine.communication_deliveries
        WHERE organization_id = %s AND communication_task_id = %s
        """,
        (organization_id, task_id),
    ).fetchone() == ([1, 2],)
    assert e2e_admin_conn.execute(
        """
        SELECT status, attempt_count = max_attempts
        FROM request_engine.scheduled_actions
        WHERE id = %s
        """,
        (exhausted_retry_id,),
    ).fetchone() == ("pending", True)
    assert e2e_admin_conn.execute(
        "SELECT status, action_version FROM request_engine.scheduled_actions WHERE id = %s",
        (malformed_retry_id,),
    ).fetchone() == ("pending", 999)


@pytest.mark.asyncio
async def test_exhausted_and_malformed_reconciliation_actions_do_not_suppress_recovery(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    organization_id = support.new_org(e2e_admin_conn, "reconcile-recovery-semantics")
    task_id = _new_task(e2e_admin_conn, organization_id)

    async with _domain_factory(worker_runtime_credentials) as session_factory:
        async with tenant_transaction(session_factory, organization_id) as session:
            prepared = await prepare_dispatch(
                session,
                organization_id=organization_id,
                communication_task_id=task_id,
            )
        assert prepared.kind is DeliveryWorkKind.SEND
        assert prepared.delivery_id is not None
        delivery_id = prepared.delivery_id

        exhausted_id = _insert_fake_action(
            e2e_admin_conn,
            organization_id,
            action_type="reconcile_delivery",
            action_version=1,
            subject_kind="CommunicationDelivery",
            subject_id=delivery_id,
            payload={"delivery_id": str(delivery_id)},
            exhausted=True,
        )
        malformed_id = _insert_fake_action(
            e2e_admin_conn,
            organization_id,
            action_type="reconcile_delivery",
            action_version=999,
            subject_kind="CommunicationDelivery",
            subject_id=delivery_id,
            payload={"delivery_id": str(uuid4())},
            exhausted=False,
        )

        async with tenant_transaction(session_factory, organization_id) as session:
            finalized = await finalize_provider_result(
                session,
                organization_id=organization_id,
                delivery_id=delivery_id,
                result=ProviderDeliveryResult(
                    status=ProviderDeliveryStatus.AMBIGUOUS,
                    retryable=False,
                    result_data={"source": "recovery-test"},
                ),
            )

    assert finalized.status is ProviderDeliveryStatus.AMBIGUOUS
    valid_reconciliation = e2e_admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.scheduled_actions
        WHERE organization_id = %s
          AND owner_module = 'communications'
          AND action_type = 'reconcile_delivery'
          AND action_version = 1
          AND subject_kind = 'CommunicationDelivery'
          AND subject_id = %s
          AND pg_catalog.pg_input_is_valid(payload ->> 'delivery_id', 'uuid')
          AND (payload ->> 'delivery_id')::uuid = %s
          AND status IN ('pending', 'leased')
          AND attempt_count < max_attempts
        """,
        (organization_id, delivery_id, delivery_id),
    ).fetchone()
    assert valid_reconciliation == (1,)
    assert e2e_admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.scheduled_actions
        WHERE organization_id = %s
          AND owner_module = 'communications'
          AND action_type = 'reconcile_delivery'
          AND subject_kind = 'CommunicationDelivery'
          AND subject_id = %s
        """,
        (organization_id, delivery_id),
    ).fetchone() == (3,)
    assert e2e_admin_conn.execute(
        "SELECT status, attempt_count = max_attempts FROM request_engine.scheduled_actions WHERE id = %s",
        (exhausted_id,),
    ).fetchone() == ("pending", True)
    assert e2e_admin_conn.execute(
        "SELECT status, action_version FROM request_engine.scheduled_actions WHERE id = %s",
        (malformed_id,),
    ).fetchone() == ("pending", 999)
