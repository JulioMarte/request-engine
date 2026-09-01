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
async def test_delivered_result_is_monotonic_against_late_nonterminal_provider_results(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    org = support.new_org(e2e_admin_conn, "delivered-monotonic")
    task_id = new_task(e2e_admin_conn, org, status="delivering")
    delivery_id = new_delivery(e2e_admin_conn, org, task_id, status="accepted")

    async with worker_stack(worker_runtime_credentials, {}) as stack:
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

        # Disposition (doc 40 T6): the late NOT_FOUND entry was removed with the
        # NOT_FOUND vocabulary itself. A provider that cannot find the attempt
        # now reports ambiguity at the transport boundary (webhook lookup 404 ->
        # AMBIGUOUS, proven in tests/modules/communications), so the ambiguous
        # case below is the surviving non-terminal late answer.
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

    assert delivery_status(e2e_admin_conn, delivery_id) == "delivered"
    assert task_status(e2e_admin_conn, task_id) == "completed"
    assert event_count(e2e_admin_conn, org, "communication.task_completed.v1", task_id) == 1
    assert event_count(e2e_admin_conn, org, "communication.task_failed.v1", task_id) == 0
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


# Disposition (doc 40 T6): the former
# ``test_reconciliation_not_found_schedules_backoff_dispatch_without_immediate_resend``
# proved that a NOT_FOUND lookup answer closed the attempt as a retryable
# failure and scheduled a backoff dispatch — protecting "a lost provider answer
# never triggers an immediate resend". The NOT_FOUND outcome vocabulary is
# retired: the webhook transport now answers a missing attempt with AMBIGUOUS
# (tests/modules/communications/test_webhook_delivery_provider.py) and an
# ambiguous result keeps the delivery reconciling without any resend (guarantee
# proven by the recovery-scheduling reconciliation proofs and
# test_send_exception_becomes_ambiguous_and_schedules_lookup_not_resend). The
# retryable-backoff-dispatch behavior itself remains proven by
# test_retryable_failure_schedules_exactly_one_future_dispatch.
