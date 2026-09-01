"""Delivery resilience proofs on the production scheduled-handler composition.

The executor under test is ``CommunicationDeliveryScheduledHandler`` composed
inside the platform ``FencedWorkerRuntime`` via ``ScheduledActionRouter`` — the
same wiring the worker bootstrap assembles for production. Claims/leases come
from the real ``PostgresScheduledActionWorker``; provider doubles stand only at
the external transport boundary.

Disposition (doc 40 T5): the retired legacy ``CommunicationDeliveryWorker``
self-reported per-execution ``detail`` strings; the scheduled handler returns
no such value because lease finalization belongs to the runtime. Every former
``outcome.detail`` assertion is therefore replaced by the equivalent durable
oracle (delivery/task/scheduled-action state), which is a strictly stronger
claim. The legacy-only executor states (DEFERRED/DEAD self-report) are replaced
by ``WorkerItemState`` outcomes from the real runtime and by durable
``scheduled_actions`` rows.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest

from request_engine.modules.communications.adapters.db.delivery_store import (
    finalize_provider_result,
    prepare_dispatch,
)
from request_engine.modules.communications.adapters.worker.scheduled_delivery import (
    CommunicationDeliveryScheduledHandler,
)
from request_engine.modules.communications.contracts.delivery import (
    ProviderDeliveryResult,
    ProviderDeliveryStatus,
)
from request_engine.platform.db.session import tenant_transaction
from request_engine.platform.scheduling.postgres import PostgresScheduledActionWorker
from request_engine.platform.worker.runtime import (
    PermanentWorkError,
    WorkerItemState,
)

from . import operational_support as support
from .delivery_provider_fakes import ScriptedProvider, UniqueDeliveredProvider
from .delivery_resilience_readers import (
    action_status,
    delivery_id_for,
    delivery_status,
    event_count,
    new_delivery,
    task_status,
)
from .delivery_resilience_store import (
    dispatch,
    new_action,
    new_task,
    reconcile,
)
from .delivery_resilience_world import (
    claim_and_process,
    delivery_runtime,
    worker_stack,
)

pytestmark = [pytest.mark.postgres, pytest.mark.e2e]


@pytest.mark.asyncio
async def test_delivered_send_completes_task_action_and_outbox(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    org = support.new_org(e2e_admin_conn, "delivery-success")
    task_id = new_task(e2e_admin_conn, org)
    action_id = dispatch(e2e_admin_conn, org, task_id)
    provider = ScriptedProvider(
        send=ProviderDeliveryResult(
            status=ProviderDeliveryStatus.DELIVERED,
            provider_message_id=f"msg-{uuid4().hex}",
        )
    )

    async with worker_stack(worker_runtime_credentials, {"provider-a": provider}) as stack:
        _, _, scheduler, handler = stack
        await claim_and_process(scheduler, handler)

    assert len(provider.send_calls) == 1
    assert provider.lookup_calls == []
    assert provider.send_calls[0].provider_idempotency_key == (f"communication:{task_id}:attempt:1")
    assert provider.send_calls[0].attempt_no == 1
    assert delivery_status(e2e_admin_conn, delivery_id_for(e2e_admin_conn, task_id)) == "delivered"
    assert task_status(e2e_admin_conn, task_id) == "completed"
    assert action_status(e2e_admin_conn, action_id) == "completed"
    assert event_count(e2e_admin_conn, org, "communication.task_completed.v1", task_id) == 1


@pytest.mark.asyncio
async def test_send_exception_becomes_ambiguous_and_schedules_lookup_not_resend(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    org = support.new_org(e2e_admin_conn, "delivery-ambiguous")
    task_id = new_task(e2e_admin_conn, org)
    action_id = dispatch(e2e_admin_conn, org, task_id)
    provider = ScriptedProvider(send=TimeoutError("provider response lost"))

    async with worker_stack(worker_runtime_credentials, {"provider-a": provider}) as stack:
        _, _, scheduler, handler = stack
        await claim_and_process(scheduler, handler)

    assert len(provider.send_calls) == 1
    assert provider.lookup_calls == []
    assert action_status(e2e_admin_conn, action_id) == "completed"
    delivery = e2e_admin_conn.execute(
        """
        SELECT id, status, result_data->>'error_phase'
        FROM request_engine.communication_deliveries
        WHERE communication_task_id = %s
        """,
        (task_id,),
    ).fetchone()
    assert delivery is not None
    delivery_id = cast(UUID, delivery[0])
    assert delivery[1:] == ("ambiguous", "send")
    reconciliations = e2e_admin_conn.execute(
        """
        SELECT subject_id, status
        FROM request_engine.scheduled_actions
        WHERE organization_id = %s AND action_type = 'reconcile_delivery'
        """,
        (org,),
    ).fetchall()
    assert reconciliations == [(delivery_id, "pending")]
    pending_resends = e2e_admin_conn.execute(
        """
        SELECT count(*) FROM request_engine.scheduled_actions
        WHERE organization_id = %s
          AND action_type = 'dispatch_task'
          AND status = 'pending'
        """,
        (org,),
    ).fetchone()
    assert pending_resends == (0,)


@pytest.mark.asyncio
async def test_reconciliation_delivered_uses_lookup_without_second_send(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    org = support.new_org(e2e_admin_conn, "delivery-reconcile")
    task_id = new_task(e2e_admin_conn, org, status="delivering")
    delivery_id = new_delivery(e2e_admin_conn, org, task_id, status="ambiguous")
    action_id = reconcile(e2e_admin_conn, org, delivery_id)
    provider = ScriptedProvider(
        lookup=ProviderDeliveryResult(
            status=ProviderDeliveryStatus.DELIVERED,
            provider_message_id=f"msg-final-{uuid4().hex}",
        )
    )

    async with worker_stack(worker_runtime_credentials, {"provider-a": provider}) as stack:
        _, _, scheduler, handler = stack
        await claim_and_process(scheduler, handler)

    assert provider.send_calls == []
    assert len(provider.lookup_calls) == 1
    assert provider.lookup_calls[0].delivery_id == delivery_id
    assert task_status(e2e_admin_conn, task_id) == "completed"
    assert delivery_status(e2e_admin_conn, delivery_id) == "delivered"
    assert action_status(e2e_admin_conn, action_id) == "completed"


@pytest.mark.asyncio
async def test_lookup_exception_retries_same_action_without_resend(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    org = support.new_org(e2e_admin_conn, "delivery-lookup-retry")
    task_id = new_task(e2e_admin_conn, org, status="delivering")
    delivery_id = new_delivery(e2e_admin_conn, org, task_id, status="accepted")
    action_id = reconcile(e2e_admin_conn, org, delivery_id)
    provider = ScriptedProvider(lookup=ConnectionError("provider unavailable"))

    async with worker_stack(worker_runtime_credentials, {"provider-a": provider}) as stack:
        _, _, scheduler, handler = stack
        runtime = delivery_runtime(scheduler, handler)
        outcomes = await runtime.run_once()

    assert len(outcomes) == 1
    assert outcomes[0].work_id == action_id
    assert outcomes[0].state is WorkerItemState.RETRY
    assert outcomes[0].detail == "lookup_ConnectionError"
    assert provider.send_calls == []
    action = e2e_admin_conn.execute(
        """
        SELECT status, claim_token, lease_until, attempt_count, last_error_class
        FROM request_engine.scheduled_actions WHERE id = %s
        """,
        (action_id,),
    ).fetchone()
    assert action == ("pending", None, None, 1, "lookup_ConnectionError")
    assert delivery_status(e2e_admin_conn, delivery_id) == "accepted"


@pytest.mark.asyncio
async def test_retryable_failure_schedules_exactly_one_future_dispatch(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    org = support.new_org(e2e_admin_conn, "delivery-retryable")
    task_id = new_task(e2e_admin_conn, org)
    original_id = dispatch(e2e_admin_conn, org, task_id)
    provider = ScriptedProvider(
        send=ProviderDeliveryResult(
            status=ProviderDeliveryStatus.FAILED,
            retryable=True,
            result_data={"error_class": "provider_503"},
        )
    )

    async with worker_stack(worker_runtime_credentials, {"provider-a": provider}) as stack:
        _, _, scheduler, handler = stack
        await claim_and_process(scheduler, handler)

    assert len(provider.send_calls) == 1
    assert delivery_status(e2e_admin_conn, delivery_id_for(e2e_admin_conn, task_id)) == "failed"
    assert task_status(e2e_admin_conn, task_id) == "pending"
    assert event_count(e2e_admin_conn, org, "communication.task_failed.v1", task_id) == 0
    assert action_status(e2e_admin_conn, original_id) == "completed"
    retries = e2e_admin_conn.execute(
        """
        SELECT status, subject_id
        FROM request_engine.scheduled_actions
        WHERE organization_id = %s
          AND action_type = 'dispatch_task'
          AND id <> %s
        """,
        (org, original_id),
    ).fetchall()
    assert retries == [("pending", task_id)]
    assert event_count(e2e_admin_conn, org, "communication.task_failed.v1", task_id) == 0


@pytest.mark.asyncio
async def test_non_retryable_failure_is_terminal_and_emits_failure_event(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    org = support.new_org(e2e_admin_conn, "delivery-terminal")
    task_id = new_task(e2e_admin_conn, org)
    action_id = dispatch(e2e_admin_conn, org, task_id)
    provider = ScriptedProvider(
        send=ProviderDeliveryResult(
            status=ProviderDeliveryStatus.FAILED,
            retryable=False,
            result_data={"error_class": "invalid_destination"},
        )
    )

    async with worker_stack(worker_runtime_credentials, {"provider-a": provider}) as stack:
        _, _, scheduler, handler = stack
        await claim_and_process(scheduler, handler)

    assert task_status(e2e_admin_conn, task_id) == "failed"
    assert action_status(e2e_admin_conn, action_id) == "completed"
    assert event_count(e2e_admin_conn, org, "communication.task_failed.v1", task_id) == 1


@pytest.mark.asyncio
async def test_missing_provider_fails_domain_state_before_dead_lettering_action(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    org = support.new_org(e2e_admin_conn, "delivery-provider-missing")
    task_id = new_task(e2e_admin_conn, org)
    action_id = dispatch(e2e_admin_conn, org, task_id)

    async with worker_stack(worker_runtime_credentials, {}) as stack:
        _, _, scheduler, handler = stack
        runtime = delivery_runtime(scheduler, handler)
        outcomes = await runtime.run_once()

    assert len(outcomes) == 1
    assert outcomes[0].work_id == action_id
    assert outcomes[0].state is WorkerItemState.DEAD
    assert outcomes[0].detail == "provider_not_configured"
    action = e2e_admin_conn.execute(
        """
        SELECT status, claim_token, lease_until, last_error_class
        FROM request_engine.scheduled_actions WHERE id = %s
        """,
        (action_id,),
    ).fetchone()
    assert action == ("dead", None, None, "provider_not_configured")
    assert task_status(e2e_admin_conn, task_id) == "failed"
    delivery = e2e_admin_conn.execute(
        """
        SELECT status, result_data->>'error_class', result_data->>'error_phase'
        FROM request_engine.communication_deliveries
        WHERE communication_task_id = %s
        """,
        (task_id,),
    ).fetchone()
    assert delivery == ("failed", "provider_not_configured", "provider_resolution")
    assert event_count(e2e_admin_conn, org, "communication.task_failed.v1", task_id) == 1


@pytest.mark.asyncio
async def test_unsupported_action_is_dead_lettered_as_permanent_poison_work(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    """A communications action the handler cannot interpret is poison: the
    orphaned task closes with a visible failure fact before the runtime fences
    the action into the dead letter (the router-level variant for actions no
    handler claims is proven in tests/integration/v3_worker_runtime)."""

    org = support.new_org(e2e_admin_conn, "delivery-poison-type")
    task_id = new_task(e2e_admin_conn, org)
    action_id = new_action(
        e2e_admin_conn,
        org,
        action_type="unknown_action",
        subject_kind="CommunicationTask",
        subject_id=task_id,
        payload={},
    )

    async with worker_stack(worker_runtime_credentials, {}) as stack:
        _, _, scheduler, handler = stack
        leases = await scheduler.claim(limit=1)
        assert len(leases) == 1
        with pytest.raises(PermanentWorkError) as exc_info:
            await handler.handle(leases[0])
        assert exc_info.value.error_class == "unsupported_communications_scheduled_action"
        assert await scheduler.dead_letter(leases[0], error_class=exc_info.value.error_class)

    row = e2e_admin_conn.execute(
        "SELECT status, last_error_class FROM request_engine.scheduled_actions WHERE id = %s",
        (action_id,),
    ).fetchone()
    assert row == ("dead", "unsupported_communications_scheduled_action")
    assert task_status(e2e_admin_conn, task_id) == "failed"
    assert event_count(e2e_admin_conn, org, "communication.task_failed.v1", task_id) == 1


@pytest.mark.asyncio
async def test_payload_identity_mismatch_dead_letters_action_and_fails_orphaned_task(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    org = support.new_org(e2e_admin_conn, "delivery-poison-payload")
    task_id = new_task(e2e_admin_conn, org)
    action_id = dispatch(e2e_admin_conn, org, task_id, payload_task_id=uuid4())

    async with worker_stack(worker_runtime_credentials, {}) as stack:
        _, _, scheduler, handler = stack
        runtime = delivery_runtime(scheduler, handler)
        outcomes = await runtime.run_once()

    assert len(outcomes) == 1
    assert outcomes[0].work_id == action_id
    assert outcomes[0].state is WorkerItemState.DEAD
    assert outcomes[0].detail == "scheduled_action_payload_mismatch"
    row = e2e_admin_conn.execute(
        "SELECT status, last_error_class FROM request_engine.scheduled_actions WHERE id = %s",
        (action_id,),
    ).fetchone()
    assert row == ("dead", "scheduled_action_payload_mismatch")
    assert task_status(e2e_admin_conn, task_id) == "failed"
    assert event_count(e2e_admin_conn, org, "communication.task_failed.v1", task_id) == 1
    delivery_count = e2e_admin_conn.execute(
        """
        SELECT count(*) FROM request_engine.communication_deliveries
        WHERE communication_task_id = %s
        """,
        (task_id,),
    ).fetchone()
    assert delivery_count == (0,)


@pytest.mark.asyncio
@pytest.mark.concurrency
async def test_crash_after_provider_finalize_before_action_ack_reclaims_without_second_send(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    org = support.new_org(e2e_admin_conn, "delivery-crash-after-finalize")
    task_id = new_task(e2e_admin_conn, org)
    action_id = dispatch(e2e_admin_conn, org, task_id)
    provider = UniqueDeliveredProvider()

    async with worker_stack(worker_runtime_credentials, {"provider-a": provider}) as stack:
        factory, _, scheduler, handler = stack
        leases = await scheduler.claim(limit=1, lease=timedelta(seconds=30))
        assert len(leases) == 1
        first_lease = leases[0]
        assert first_lease.id == action_id

        async with tenant_transaction(factory, org) as session:
            prepared = await prepare_dispatch(
                session,
                organization_id=org,
                communication_task_id=task_id,
            )
        assert prepared.send_request is not None
        provider_result = await provider.send(prepared.send_request)
        assert prepared.delivery_id is not None
        async with tenant_transaction(factory, org) as session:
            finalized = await finalize_provider_result(
                session,
                organization_id=org,
                delivery_id=prepared.delivery_id,
                result=provider_result,
            )
        assert finalized.status is ProviderDeliveryStatus.DELIVERED
        assert task_status(e2e_admin_conn, task_id) == "completed"
        assert action_status(e2e_admin_conn, action_id) != "completed"

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

        await handler.handle(reclaimed[0])
        assert await scheduler.complete(reclaimed[0]) is True
        assert await scheduler.complete(first_lease) is False

    assert len(provider.send_calls) == 1
    assert provider.lookup_calls == []
    assert action_status(e2e_admin_conn, action_id) == "completed"
    delivery_count = e2e_admin_conn.execute(
        """
        SELECT count(*) FROM request_engine.communication_deliveries
        WHERE communication_task_id = %s
        """,
        (task_id,),
    ).fetchone()
    assert delivery_count == (1,)
    assert event_count(e2e_admin_conn, org, "communication.task_completed.v1", task_id) == 1


@pytest.mark.asyncio
@pytest.mark.concurrency
async def test_crash_after_prepare_reconciles_existing_attempt_before_any_resend(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    org = support.new_org(e2e_admin_conn, "delivery-crash-after-prepare")
    task_id = new_task(e2e_admin_conn, org)
    action_id = dispatch(e2e_admin_conn, org, task_id)
    provider = ScriptedProvider(
        lookup=ProviderDeliveryResult(
            status=ProviderDeliveryStatus.DELIVERED,
            provider_message_id=f"reconciled-{uuid4().hex}",
        )
    )

    async with worker_stack(worker_runtime_credentials, {"provider-a": provider}) as stack:
        factory, _, scheduler, handler = stack
        leases = await scheduler.claim(limit=1, lease=timedelta(seconds=30))
        assert len(leases) == 1
        first_lease = leases[0]

        async with tenant_transaction(factory, org) as session:
            prepared = await prepare_dispatch(
                session,
                organization_id=org,
                communication_task_id=task_id,
            )
        assert prepared.delivery_id is not None
        assert prepared.send_request is not None

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
        assert reclaimed[0].claim_token != first_lease.claim_token
        await handler.handle(reclaimed[0])
        assert await scheduler.complete(reclaimed[0]) is True

    assert provider.send_calls == []
    assert len(provider.lookup_calls) == 1
    assert provider.lookup_calls[0].delivery_id == prepared.delivery_id
    assert task_status(e2e_admin_conn, task_id) == "completed"
    assert delivery_status(e2e_admin_conn, prepared.delivery_id) == "delivered"
    assert action_status(e2e_admin_conn, action_id) == "completed"
    assert event_count(e2e_admin_conn, org, "communication.task_completed.v1", task_id) == 1


@pytest.mark.asyncio
@pytest.mark.concurrency
async def test_three_delivery_runtimes_claim_disjoint_work_and_each_task_sends_once(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    org = support.new_org(e2e_admin_conn, "delivery-contention")
    task_ids = tuple(new_task(e2e_admin_conn, org) for _ in range(12))
    action_ids = tuple(dispatch(e2e_admin_conn, org, task_id) for task_id in task_ids)
    provider = UniqueDeliveredProvider()

    async with worker_stack(worker_runtime_credentials, {"provider-a": provider}) as stack:
        domain_factory, worker_factory, _, _ = stack
        schedulers = tuple(PostgresScheduledActionWorker(worker_factory) for _ in range(3))
        handlers = tuple(
            CommunicationDeliveryScheduledHandler(
                domain_factory,
                scheduler,
                {"provider-a": provider},
            )
            for scheduler in schedulers
        )
        runtimes = tuple(
            delivery_runtime(scheduler, handler, batch=4)
            for scheduler, handler in zip(schedulers, handlers, strict=True)
        )
        outcome_groups = await asyncio.gather(*(runtime.run_once() for runtime in runtimes))
        outcomes = tuple(outcome for group in outcome_groups for outcome in group)

    assert len(outcomes) == 12
    assert {outcome.work_id for outcome in outcomes} == set(action_ids)
    assert all(outcome.state is WorkerItemState.COMPLETED for outcome in outcomes)
    assert len(provider.send_calls) == 12
    assert provider.lookup_calls == []
    assert len({call.provider_idempotency_key for call in provider.send_calls}) == 12
    for task_id in task_ids:
        assert task_status(e2e_admin_conn, task_id) == "completed"
        assert event_count(e2e_admin_conn, org, "communication.task_completed.v1", task_id) == 1
    for action_id in action_ids:
        assert action_status(e2e_admin_conn, action_id) == "completed"
