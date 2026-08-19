# pyright: reportPrivateUsage=false

from typing import cast
from uuid import UUID, uuid4

import pytest

from request_engine.modules.communications.adapters.db.delivery_store import (
    finalize_provider_result,
)
from request_engine.modules.communications.contracts.delivery import (
    ProviderDeliveryResult,
    ProviderDeliveryStatus,
)
from request_engine.platform.db.session import tenant_transaction

from . import operational_support as support
from .test_communication_worker_resilience import (
    PAST,
    ScriptedProvider,
    _action_status,
    _claim_and_process,
    _delivery,
    _delivery_status,
    _events,
    _reconcile,
    _task,
    _task_status,
    _worker_stack,
)

pytestmark = [pytest.mark.postgres, pytest.mark.e2e]


@pytest.mark.asyncio
async def test_delivered_result_is_monotonic_against_late_nonterminal_provider_results(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    org = support.new_org(e2e_admin_conn, "delivered-monotonic")
    task_id = _task(e2e_admin_conn, org, status="delivering")
    delivery_id = _delivery(e2e_admin_conn, org, task_id, status="accepted")

    async with _worker_stack(worker_runtime_credentials, {}) as stack:
        domain_factory, _, _, _ = stack
        async with tenant_transaction(domain_factory, org) as session:
            first = await finalize_provider_result(
                session,
                organization_id=org,
                delivery_id=delivery_id,
                result=ProviderDeliveryResult(
                    status=ProviderDeliveryStatus.DELIVERED,
                    provider_message_id=f"delivered-{uuid4().hex}",
                ),
            )
        assert first.status is ProviderDeliveryStatus.DELIVERED

        late_results = (
            ProviderDeliveryResult(status=ProviderDeliveryStatus.ACCEPTED),
            ProviderDeliveryResult(status=ProviderDeliveryStatus.AMBIGUOUS),
            ProviderDeliveryResult(
                status=ProviderDeliveryStatus.FAILED,
                retryable=True,
                result_data={"error_class": "late_retryable_failure"},
            ),
            ProviderDeliveryResult(
                status=ProviderDeliveryStatus.FAILED,
                retryable=False,
                result_data={"error_class": "late_terminal_failure"},
            ),
            ProviderDeliveryResult(status=ProviderDeliveryStatus.NOT_FOUND),
        )
        for late in late_results:
            async with tenant_transaction(domain_factory, org) as session:
                replay = await finalize_provider_result(
                    session,
                    organization_id=org,
                    delivery_id=delivery_id,
                    result=late,
                )
            assert replay.status is ProviderDeliveryStatus.DELIVERED
            assert replay.task_terminal is True

    assert _delivery_status(e2e_admin_conn, delivery_id) == "delivered"
    assert _task_status(e2e_admin_conn, task_id) == "completed"
    assert _events(e2e_admin_conn, org, "communication.task_completed.v1", task_id) == 1
    assert _events(e2e_admin_conn, org, "communication.task_failed.v1", task_id) == 0
    assert e2e_admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.scheduled_actions
        WHERE organization_id = %s
          AND subject_id IN (%s, %s)
          AND action_type IN ('dispatch_task', 'reconcile_delivery')
          AND status IN ('pending', 'leased')
        """,
        (org, task_id, delivery_id),
    ).fetchone() == (0,)


@pytest.mark.asyncio
async def test_reconciliation_not_found_schedules_backoff_dispatch_without_immediate_resend(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    org = support.new_org(e2e_admin_conn, "reconcile-not-found")
    task_id = _task(e2e_admin_conn, org, status="delivering")
    delivery_id = _delivery(e2e_admin_conn, org, task_id, status="ambiguous")
    reconcile_id = _reconcile(e2e_admin_conn, org, delivery_id)
    provider = ScriptedProvider(
        lookup=ProviderDeliveryResult(
            status=ProviderDeliveryStatus.NOT_FOUND,
            provider_message_id=f"missing-{uuid4().hex}",
        )
    )

    async with _worker_stack(worker_runtime_credentials, {"provider-a": provider}) as stack:
        _, _, scheduler, worker = stack
        outcome = await _claim_and_process(scheduler, worker)

    assert outcome.detail == "failed"
    assert provider.send_calls == []
    assert len(provider.lookup_calls) == 1
    assert _action_status(e2e_admin_conn, reconcile_id) == "completed"
    assert _delivery_status(e2e_admin_conn, delivery_id) == "failed"
    assert _task_status(e2e_admin_conn, task_id) == "pending"

    delivery = e2e_admin_conn.execute(
        """
        SELECT result_data->>'retryable', result_data->>'reconciliation'
        FROM request_engine.communication_deliveries
        WHERE id = %s
        """,
        (delivery_id,),
    ).fetchone()
    assert delivery == ("true", "not_found")

    retry = e2e_admin_conn.execute(
        """
        SELECT id, status, execute_at > clock_timestamp()
        FROM request_engine.scheduled_actions
        WHERE organization_id = %s
          AND action_type = 'dispatch_task'
          AND subject_kind = 'CommunicationTask'
          AND subject_id = %s
          AND status = 'pending'
        """,
        (org, task_id),
    ).fetchone()
    assert retry is not None
    retry_id = cast(UUID, retry[0])
    assert retry[1:] == ("pending", True)

    # Making the retry due is the explicit boundary at which a new send is allowed.
    e2e_admin_conn.execute(
        """
        UPDATE request_engine.scheduled_actions
        SET execute_at = %s, next_attempt_at = %s
        WHERE id = %s
        """,
        (PAST, PAST, retry_id),
    )
