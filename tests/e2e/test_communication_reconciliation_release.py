# pyright: reportPrivateUsage=false

from datetime import timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest

from request_engine.modules.communications.adapters.db.delivery_store import (
    finalize_provider_result,
    prepare_dispatch,
)
from request_engine.modules.communications.contracts.delivery import (
    ProviderDeliveryResult,
    ProviderDeliveryStatus,
)
from request_engine.platform.db.session import tenant_transaction

from . import operational_support as support
from .delivery_provider_fakes import ScriptedProvider
from .delivery_resilience_readers import action_status, delivery_status, event_count, task_status
from .delivery_resilience_store import dispatch, new_task
from .delivery_resilience_world import PAST, claim_and_process, worker_stack

pytestmark = [pytest.mark.postgres, pytest.mark.e2e]


@pytest.mark.asyncio
@pytest.mark.concurrency
async def test_repeated_accepted_reconciliation_reuses_one_future_action_before_delivery(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    org = support.new_org(e2e_admin_conn, "accepted-reconciliation")
    task_id = new_task(e2e_admin_conn, org)
    dispatch_id = dispatch(e2e_admin_conn, org, task_id)
    provider = ScriptedProvider(
        send=ProviderDeliveryResult(
            status=ProviderDeliveryStatus.ACCEPTED,
            provider_message_id=f"accepted-{uuid4().hex}",
        ),
        lookup=ProviderDeliveryResult(
            status=ProviderDeliveryStatus.ACCEPTED,
            provider_message_id=f"accepted-{uuid4().hex}",
        ),
    )

    async with worker_stack(worker_runtime_credentials, {"provider-a": provider}) as stack:
        _, _, scheduler, handler = stack
        await claim_and_process(scheduler, handler)
        assert action_status(e2e_admin_conn, dispatch_id) == "completed"
        assert len(provider.send_calls) == 1
        assert provider.lookup_calls == []

        delivery_row = e2e_admin_conn.execute(
            """
            SELECT id, status
            FROM request_engine.communication_deliveries
            WHERE organization_id = %s AND communication_task_id = %s
            """,
            (org, task_id),
        ).fetchone()
        assert delivery_row is not None
        delivery_id = cast(UUID, delivery_row[0])
        assert delivery_row[1] == "accepted"

        reconcile_row = e2e_admin_conn.execute(
            """
            SELECT id
            FROM request_engine.scheduled_actions
            WHERE organization_id = %s
              AND action_type = 'reconcile_delivery'
              AND subject_kind = 'CommunicationDelivery'
              AND subject_id = %s
              AND status = 'pending'
            """,
            (org, delivery_id),
        ).fetchone()
        assert reconcile_row is not None
        first_reconcile_id = cast(UUID, reconcile_row[0])
        e2e_admin_conn.execute(
            """
            UPDATE request_engine.scheduled_actions
            SET execute_at = %s, next_attempt_at = %s
            WHERE id = %s
            """,
            (PAST, PAST, first_reconcile_id),
        )

        await claim_and_process(scheduler, handler)
        assert len(provider.send_calls) == 1
        assert len(provider.lookup_calls) == 1
        assert delivery_status(e2e_admin_conn, delivery_id) == "accepted"

        pending_reconciliations = e2e_admin_conn.execute(
            """
            SELECT id
            FROM request_engine.scheduled_actions
            WHERE organization_id = %s
              AND action_type = 'reconcile_delivery'
              AND subject_kind = 'CommunicationDelivery'
              AND subject_id = %s
              AND status = 'pending'
            ORDER BY created_at, id
            """,
            (org, delivery_id),
        ).fetchall()
        assert len(pending_reconciliations) == 1
        next_reconcile_id = cast(UUID, pending_reconciliations[0][0])

        replay_dispatch_id = dispatch(e2e_admin_conn, org, task_id)
        await claim_and_process(scheduler, handler)
        assert action_status(e2e_admin_conn, replay_dispatch_id) == "completed"
        assert len(provider.send_calls) == 1
        assert len(provider.lookup_calls) == 2
        assert delivery_status(e2e_admin_conn, delivery_id) == "accepted"

        still_one_future = e2e_admin_conn.execute(
            """
            SELECT id
            FROM request_engine.scheduled_actions
            WHERE organization_id = %s
              AND action_type = 'reconcile_delivery'
              AND subject_kind = 'CommunicationDelivery'
              AND subject_id = %s
              AND status = 'pending'
            """,
            (org, delivery_id),
        ).fetchall()
        assert still_one_future == [(next_reconcile_id,)]

        provider.lookup_result = ProviderDeliveryResult(
            status=ProviderDeliveryStatus.DELIVERED,
            provider_message_id=f"delivered-{uuid4().hex}",
        )
        e2e_admin_conn.execute(
            """
            UPDATE request_engine.scheduled_actions
            SET execute_at = %s, next_attempt_at = %s
            WHERE id = %s
            """,
            (PAST, PAST, next_reconcile_id),
        )
        await claim_and_process(scheduler, handler)

    assert len(provider.send_calls) == 1
    assert len(provider.lookup_calls) == 3
    assert task_status(e2e_admin_conn, task_id) == "completed"
    assert delivery_status(e2e_admin_conn, delivery_id) == "delivered"
    assert event_count(e2e_admin_conn, org, "communication.task_completed.v1", task_id) == 1
    assert e2e_admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.scheduled_actions
        WHERE organization_id = %s
          AND action_type = 'reconcile_delivery'
          AND subject_id = %s
          AND status IN ('pending', 'leased')
        """,
        (org, delivery_id),
    ).fetchone() == (0,)


@pytest.mark.asyncio
@pytest.mark.concurrency
async def test_crash_after_retryable_failure_finalize_cannot_bypass_future_dispatch_backoff(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    org = support.new_org(e2e_admin_conn, "retry-backoff-replay")
    task_id = new_task(e2e_admin_conn, org)
    action_id = dispatch(e2e_admin_conn, org, task_id)
    provider = ScriptedProvider(
        send=ProviderDeliveryResult(
            status=ProviderDeliveryStatus.FAILED,
            retryable=True,
            result_data={"error_class": "provider_503"},
        )
    )

    async with worker_stack(worker_runtime_credentials, {"provider-a": provider}) as stack:
        domain_factory, _, scheduler, handler = stack
        leases = await scheduler.claim(limit=1, lease=timedelta(seconds=30))
        assert len(leases) == 1
        first_lease = leases[0]
        assert first_lease.id == action_id

        async with tenant_transaction(domain_factory, org) as session:
            prepared = await prepare_dispatch(
                session,
                organization_id=org,
                communication_task_id=task_id,
            )
        assert prepared.delivery_id is not None
        assert prepared.send_request is not None
        provider_result = await provider.send(prepared.send_request)
        async with tenant_transaction(domain_factory, org) as session:
            finalized = await finalize_provider_result(
                session,
                organization_id=org,
                delivery_id=prepared.delivery_id,
                result=provider_result,
            )
        assert finalized.status is ProviderDeliveryStatus.FAILED
        assert finalized.retryable is True
        assert task_status(e2e_admin_conn, task_id) == "pending"
        assert action_status(e2e_admin_conn, action_id) == "leased"

        retry_row = e2e_admin_conn.execute(
            """
            SELECT id, execute_at > clock_timestamp(), status
            FROM request_engine.scheduled_actions
            WHERE organization_id = %s
              AND action_type = 'dispatch_task'
              AND subject_kind = 'CommunicationTask'
              AND subject_id = %s
              AND id <> %s
            """,
            (org, task_id, action_id),
        ).fetchone()
        assert retry_row is not None
        retry_id = cast(UUID, retry_row[0])
        assert retry_row[1:] == (True, "pending")

        e2e_admin_conn.execute(
            """
            UPDATE request_engine.scheduled_actions
            SET lease_until = clock_timestamp() - interval '1 second'
            WHERE id = %s
            """,
            (action_id,),
        )
        reclaimed = await scheduler.claim(limit=1)
        assert len(reclaimed) == 1
        assert reclaimed[0].id == action_id
        assert reclaimed[0].claim_token != first_lease.claim_token

        # The replay must observe the already-scheduled future dispatch and skip
        # without another provider send or a second delivery row.
        await handler.handle(reclaimed[0])
        assert await scheduler.complete(reclaimed[0]) is True
        assert await scheduler.complete(first_lease) is False

    assert len(provider.send_calls) == 1
    assert provider.lookup_calls == []
    assert action_status(e2e_admin_conn, action_id) == "completed"
    assert e2e_admin_conn.execute(
        """
        SELECT status, execute_at > clock_timestamp()
        FROM request_engine.scheduled_actions
        WHERE id = %s
        """,
        (retry_id,),
    ).fetchone() == ("pending", True)
    assert e2e_admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.communication_deliveries
        WHERE organization_id = %s AND communication_task_id = %s
        """,
        (org, task_id),
    ).fetchone() == (1,)
