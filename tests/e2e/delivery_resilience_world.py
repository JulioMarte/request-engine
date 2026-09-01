"""Production worker-composition helpers shared by the communication delivery
e2e suites (scheduled handler inside the platform ``FencedWorkerRuntime``)."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from request_engine.entrypoints.worker.scheduled_router import ScheduledActionRouter
from request_engine.modules.communications.adapters.db.delivery_store import (
    DISPATCH_ACTION_TYPE,
    DISPATCH_ACTION_VERSION,
    RECONCILE_ACTION_TYPE,
    RECONCILE_ACTION_VERSION,
)
from request_engine.modules.communications.adapters.worker.scheduled_delivery import (
    CommunicationDeliveryScheduledHandler,
)
from request_engine.modules.communications.contracts.delivery import CommunicationDeliveryProvider
from request_engine.platform.db.session import (
    SessionFactory,
    create_postgres_engine,
    create_session_factory,
)
from request_engine.platform.scheduling.postgres import (
    PostgresScheduledActionWorker,
    ScheduledActionLease,
)
from request_engine.platform.worker.runtime import (
    FencedWorkerRuntime,
    PermanentWorkError,
    WorkerRuntimeConfig,
)

from . import operational_support as support

PAST = datetime(2000, 1, 1, tzinfo=UTC)
POLICY = {
    "channels": ["email"],
    "provider_key": "provider-a",
    "reconcile_after_seconds": 30,
    "retry_after_seconds": 30,
}


def single_action_config() -> WorkerRuntimeConfig:
    return WorkerRuntimeConfig(
        max_concurrency=1,
        claim_batch_size=1,
        lease_duration=timedelta(seconds=30),
        heartbeat_interval=timedelta(seconds=10),
        idle_sleep=timedelta(milliseconds=1),
        retry_base=timedelta(seconds=5),
        retry_cap=timedelta(minutes=1),
    )


def delivery_runtime(
    scheduler: PostgresScheduledActionWorker,
    handler: CommunicationDeliveryScheduledHandler,
    *,
    batch: int = 1,
) -> FencedWorkerRuntime[ScheduledActionLease]:
    router = ScheduledActionRouter(
        {
            ("communications", DISPATCH_ACTION_TYPE, DISPATCH_ACTION_VERSION): handler.handle,
            ("communications", RECONCILE_ACTION_TYPE, RECONCILE_ACTION_VERSION): handler.handle,
        }
    )
    config = replace(single_action_config(), max_concurrency=batch, claim_batch_size=batch)
    return FencedWorkerRuntime(scheduler, router, config=config)


@asynccontextmanager
async def worker_stack(
    credentials: support.RuntimeCredentialsLike,
    providers: Mapping[str, CommunicationDeliveryProvider],
) -> AsyncGenerator[
    tuple[
        SessionFactory,
        SessionFactory,
        PostgresScheduledActionWorker,
        CommunicationDeliveryScheduledHandler,
    ],
]:
    domain_database_url = getattr(credentials, "domain_database_url", None)
    assert domain_database_url is not None, "delivery work requires separate app credentials"
    worker_engine = create_postgres_engine(credentials.database_url)
    domain_engine = create_postgres_engine(domain_database_url)
    worker_factory: SessionFactory = create_session_factory(worker_engine)
    domain_factory: SessionFactory = create_session_factory(domain_engine)
    scheduler = PostgresScheduledActionWorker(worker_factory)
    handler = CommunicationDeliveryScheduledHandler(domain_factory, scheduler, providers)
    try:
        yield (domain_factory, worker_factory, scheduler, handler)
    finally:
        await domain_engine.dispose()
        await worker_engine.dispose()


async def claim_and_process(
    scheduler: PostgresScheduledActionWorker,
    handler: CommunicationDeliveryScheduledHandler,
) -> None:
    """Claim one action, execute the handler, and acknowledge the lease.

    The explicit ``complete`` mirrors the runtime's post-success finalization;
    a ``False`` here would mean the handler lost its fence and must fail.
    """

    leases = await scheduler.claim(limit=1)
    assert len(leases) == 1
    await handler.handle(leases[0])
    assert await scheduler.complete(leases[0]) is True


async def fail_poisoned_action(
    scheduler: PostgresScheduledActionWorker,
    handler: CommunicationDeliveryScheduledHandler,
    lease: ScheduledActionLease,
) -> str:
    """Drive poison work to its typed permanent failure, then fence the action
    into the dead letter exactly as the ``FencedWorkerRuntime`` does for a
    ``PermanentWorkError``."""

    with pytest.raises(PermanentWorkError) as exc_info:
        await handler.handle(lease)
    assert await scheduler.dead_letter(lease, error_class=exc_info.value.error_class)
    return exc_info.value.error_class
