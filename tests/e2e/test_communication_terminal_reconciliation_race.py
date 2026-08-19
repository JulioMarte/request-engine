# pyright: reportPrivateUsage=false

import asyncio
from datetime import timedelta
from uuid import UUID, uuid4

import pytest

from request_engine.modules.communications.adapters.db.delivery_store import (
    finalize_provider_result,
)
from request_engine.modules.communications.contracts.delivery import (
    CommunicationDeliveryProvider,
    ProviderDeliveryResult,
    ProviderDeliveryStatus,
    ProviderLookupRequest,
    ProviderSendRequest,
)
from request_engine.platform.db.session import tenant_transaction

from . import operational_support as support
from .test_communication_worker_resilience import (
    PAST,
    _action_status,
    _delivery,
    _delivery_status,
    _events,
    _reconcile,
    _task,
    _task_status,
    _worker_stack,
)

pytestmark = [pytest.mark.postgres, pytest.mark.e2e]


class OrderedConflictingLookupProvider(CommunicationDeliveryProvider):
    def __init__(self) -> None:
        self.lookup_calls: list[ProviderLookupRequest] = []
        self.first_started = asyncio.Event()
        self.second_started = asyncio.Event()
        self.release_failure = asyncio.Event()
        self.release_delivered = asyncio.Event()

    async def send(self, request: ProviderSendRequest) -> ProviderDeliveryResult:
        del request
        raise AssertionError("reconciliation race must never call provider.send")

    async def lookup(self, request: ProviderLookupRequest) -> ProviderDeliveryResult:
        self.lookup_calls.append(request)
        call_no = len(self.lookup_calls)
        if call_no == 1:
            self.first_started.set()
            await self.release_failure.wait()
            return ProviderDeliveryResult(
                status=ProviderDeliveryStatus.FAILED,
                retryable=False,
                result_data={"error_class": "provider_terminal_failure"},
            )
        if call_no == 2:
            self.second_started.set()
            await self.release_delivered.wait()
            return ProviderDeliveryResult(
                status=ProviderDeliveryStatus.DELIVERED,
                provider_message_id=f"late-delivered-{uuid4().hex}",
            )
        raise AssertionError("unexpected third provider.lookup call")


@pytest.mark.asyncio
@pytest.mark.concurrency
async def test_two_reconciliations_cannot_emit_failed_then_completed_for_one_delivery(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    org = support.new_org(e2e_admin_conn, "terminal-reconcile-race")
    task_id = _task(e2e_admin_conn, org, status="delivering")
    delivery_id = _delivery(e2e_admin_conn, org, task_id, status="accepted")
    first_action_id = _reconcile(e2e_admin_conn, org, delivery_id)
    second_action_id = _reconcile(e2e_admin_conn, org, delivery_id)
    target_ids = {first_action_id, second_action_id}
    provider = OrderedConflictingLookupProvider()

    async with _worker_stack(worker_runtime_credentials, {"provider-a": provider}) as stack:
        _, _, scheduler, worker = stack
        leases = await scheduler.claim(limit=500, lease=timedelta(seconds=30))
        ours = {lease.id: lease for lease in leases if lease.id in target_ids}
        assert set(ours) == target_ids

        first_process = asyncio.create_task(worker.process(ours[first_action_id]))
        await asyncio.wait_for(provider.first_started.wait(), timeout=10)

        second_process = asyncio.create_task(worker.process(ours[second_action_id]))
        await asyncio.wait_for(provider.second_started.wait(), timeout=10)

        provider.release_failure.set()
        first_outcome = await asyncio.wait_for(first_process, timeout=10)
        assert first_outcome.detail == "failed"
        assert _task_status(e2e_admin_conn, task_id) == "failed"
        assert _delivery_status(e2e_admin_conn, delivery_id) == "failed"
        assert _events(e2e_admin_conn, org, "communication.task_failed.v1", task_id) == 1
        assert _events(e2e_admin_conn, org, "communication.task_completed.v1", task_id) == 0

        provider.release_delivered.set()
        second_outcome = await asyncio.wait_for(second_process, timeout=10)

    assert second_outcome.detail == "failed"
    assert len(provider.lookup_calls) == 2
    assert _action_status(e2e_admin_conn, first_action_id) == "completed"
    assert _action_status(e2e_admin_conn, second_action_id) == "completed"
    assert _task_status(e2e_admin_conn, task_id) == "failed"
    assert _delivery_status(e2e_admin_conn, delivery_id) == "failed"
    assert _events(e2e_admin_conn, org, "communication.task_failed.v1", task_id) == 1
    assert _events(e2e_admin_conn, org, "communication.task_completed.v1", task_id) == 0


@pytest.mark.asyncio
async def test_retryable_failed_delivery_can_recover_from_late_delivered_evidence(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    org = support.new_org(e2e_admin_conn, "retryable-late-delivery")
    task_id = _task(e2e_admin_conn, org, status="delivering")
    delivery_id = _delivery(e2e_admin_conn, org, task_id, status="accepted")

    async with _worker_stack(worker_runtime_credentials, {}) as stack:
        domain_factory, _, scheduler, worker = stack
        async with tenant_transaction(domain_factory, org) as session:
            failed = await finalize_provider_result(
                session,
                organization_id=org,
                delivery_id=delivery_id,
                result=ProviderDeliveryResult(
                    status=ProviderDeliveryStatus.FAILED,
                    retryable=True,
                    result_data={"error_class": "provider_retryable_failure"},
                ),
            )
        assert failed.status is ProviderDeliveryStatus.FAILED
        assert failed.retryable is True
        assert failed.task_terminal is False
        assert _task_status(e2e_admin_conn, task_id) == "pending"
        assert _events(e2e_admin_conn, org, "communication.task_failed.v1", task_id) == 0

        async with tenant_transaction(domain_factory, org) as session:
            recovered = await finalize_provider_result(
                session,
                organization_id=org,
                delivery_id=delivery_id,
                result=ProviderDeliveryResult(
                    status=ProviderDeliveryStatus.DELIVERED,
                    provider_message_id=f"recovered-{uuid4().hex}",
                ),
            )
        assert recovered.status is ProviderDeliveryStatus.DELIVERED
        assert recovered.retryable is False
        assert recovered.task_terminal is True

        retry_row = e2e_admin_conn.execute(
            """
            SELECT id
            FROM request_engine.scheduled_actions
            WHERE organization_id = %s
              AND action_type = 'dispatch_task'
              AND subject_kind = 'CommunicationTask'
              AND subject_id = %s
              AND status = 'pending'
            """,
            (org, task_id),
        ).fetchone()
        assert retry_row is not None
        retry_id = UUID(str(retry_row[0]))
        e2e_admin_conn.execute(
            """
            UPDATE request_engine.scheduled_actions
            SET execute_at = %s, next_attempt_at = %s
            WHERE id = %s
            """,
            (PAST, PAST, retry_id),
        )
        leases = await scheduler.claim(limit=500)
        retry_lease = next(lease for lease in leases if lease.id == retry_id)
        skipped = await worker.process(retry_lease)

    assert skipped.detail == "task_completed"
    assert _action_status(e2e_admin_conn, retry_id) == "completed"
    assert _task_status(e2e_admin_conn, task_id) == "completed"
    assert _delivery_status(e2e_admin_conn, delivery_id) == "delivered"
    assert _events(e2e_admin_conn, org, "communication.task_failed.v1", task_id) == 0
    assert _events(e2e_admin_conn, org, "communication.task_completed.v1", task_id) == 1
