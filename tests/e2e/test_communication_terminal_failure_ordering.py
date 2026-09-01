# pyright: reportPrivateUsage=false

from uuid import uuid4

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
from .delivery_resilience_readers import delivery_status, event_count, new_delivery, task_status
from .delivery_resilience_store import new_task
from .delivery_resilience_world import worker_stack

pytestmark = [pytest.mark.postgres, pytest.mark.e2e]


@pytest.mark.asyncio
async def test_non_retryable_failure_is_terminal_against_late_delivered_result(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    org = support.new_org(e2e_admin_conn, "terminal-failure-ordering")
    task_id = new_task(e2e_admin_conn, org, status="delivering")
    delivery_id = new_delivery(e2e_admin_conn, org, task_id, status="accepted")

    async with worker_stack(worker_runtime_credentials, {}) as stack:
        domain_factory, _, _, _ = stack
        async with tenant_transaction(domain_factory, org) as session:
            failed = await finalize_provider_result(
                session,
                organization_id=org,
                delivery_id=delivery_id,
                result=ProviderDeliveryResult(
                    status=ProviderDeliveryStatus.FAILED,
                    retryable=False,
                    result_data={"error_class": "invalid_destination"},
                ),
            )
        assert failed.status is ProviderDeliveryStatus.FAILED
        assert failed.retryable is False
        assert failed.task_terminal is True

        async with tenant_transaction(domain_factory, org) as session:
            late = await finalize_provider_result(
                session,
                organization_id=org,
                delivery_id=delivery_id,
                result=ProviderDeliveryResult(
                    status=ProviderDeliveryStatus.DELIVERED,
                    provider_message_id=f"late-delivered-{uuid4().hex}",
                ),
            )

    assert late.status is ProviderDeliveryStatus.FAILED
    assert late.retryable is False
    assert late.task_terminal is True
    assert delivery_status(e2e_admin_conn, delivery_id) == "failed"
    assert task_status(e2e_admin_conn, task_id) == "failed"
    assert event_count(e2e_admin_conn, org, "communication.task_failed.v1", task_id) == 1
    assert event_count(e2e_admin_conn, org, "communication.task_completed.v1", task_id) == 0
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
