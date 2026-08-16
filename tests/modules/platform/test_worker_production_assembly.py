from collections.abc import Callable
from datetime import timedelta
from typing import cast

import pytest

from request_engine.bootstrap import worker as worker_bootstrap
from request_engine.entrypoints.worker.outbox_runtime import OutboxEvent
from request_engine.modules.booking.adapters.worker.no_show import NoShowScheduledHandler
from request_engine.modules.queue.adapters.worker.slot_offer_expiry import (
    SlotOfferExpiryScheduledHandler,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.worker.runtime import WorkerRuntimeConfig


class _Publisher:
    async def publish(self, event: OutboxEvent) -> None:
        del event


class _ScheduledHandler:
    async def handle(self, lease: object) -> None:
        del lease


class _CapturedRuntime:
    def __init__(self, store: object, processor: object, **kwargs: object) -> None:
        self.store = store
        self.processor = processor
        self.kwargs = kwargs

    async def run_once(self) -> tuple[object, ...]:
        return ()

    async def run_forever(self, stop_event: object) -> None:
        del stop_event


class _ProviderStore:
    async def reject(self, lease: object, *, error_class: str) -> bool:
        del lease, error_class
        return True


@pytest.mark.unit
def test_production_assembly_separates_worker_and_domain_factories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker_factory = cast(SessionFactory, object())
    domain_factory = cast(SessionFactory, object())
    handler_factories_seen: list[SessionFactory] = []
    store_factories_seen: list[tuple[str, SessionFactory]] = []
    runtimes: list[_CapturedRuntime] = []

    def no_show_factory(factory: SessionFactory) -> NoShowScheduledHandler:
        handler_factories_seen.append(factory)
        return cast(NoShowScheduledHandler, _ScheduledHandler())

    def slot_offer_factory(factory: SessionFactory) -> SlotOfferExpiryScheduledHandler:
        handler_factories_seen.append(factory)
        return cast(SlotOfferExpiryScheduledHandler, _ScheduledHandler())

    def scheduled_store(factory: SessionFactory) -> object:
        store_factories_seen.append(("scheduled", factory))
        return object()

    def outbox_store(factory: SessionFactory) -> object:
        store_factories_seen.append(("outbox", factory))
        return object()

    def provider_store(factory: SessionFactory) -> _ProviderStore:
        store_factories_seen.append(("provider", factory))
        return _ProviderStore()

    def capture_runtime(store: object, processor: object, **kwargs: object) -> _CapturedRuntime:
        runtime = _CapturedRuntime(store, processor, **kwargs)
        runtimes.append(runtime)
        return runtime

    monkeypatch.setattr(worker_bootstrap, "PostgresScheduledActionWorker", scheduled_store)
    monkeypatch.setattr(worker_bootstrap, "PostgresOutboxWorker", outbox_store)
    monkeypatch.setattr(worker_bootstrap, "PostgresProviderEventWorker", provider_store)
    monkeypatch.setattr(worker_bootstrap, "FencedWorkerRuntime", capture_runtime)

    process = worker_bootstrap.build_worker_process(
        worker_session_factory=worker_factory,
        domain_session_factory=domain_factory,
        no_show_factory=no_show_factory,
        slot_offer_expiry_factory=slot_offer_factory,
        communication_providers={},
        outbox_publisher=_Publisher(),
        outbox_internal_handlers={},
        provider_event_handlers={},
    )

    assert process.stream_names == ("scheduled_actions", "outbox_messages", "provider_events")
    assert handler_factories_seen == [domain_factory, domain_factory]
    assert store_factories_seen == [
        ("scheduled", worker_factory),
        ("outbox", worker_factory),
        ("provider", worker_factory),
    ]
    assert runtimes[2].kwargs["rejecter"] is not None


@pytest.mark.unit
def test_production_assembly_rejects_reused_session_factory() -> None:
    shared_factory = cast(SessionFactory, object())

    with pytest.raises(ValueError, match="must be distinct factories"):
        worker_bootstrap.build_worker_process(
            worker_session_factory=shared_factory,
            domain_session_factory=shared_factory,
            no_show_factory=lambda _: cast(NoShowScheduledHandler, _ScheduledHandler()),
            slot_offer_expiry_factory=lambda _: cast(
                SlotOfferExpiryScheduledHandler, _ScheduledHandler()
            ),
            communication_providers={},
            outbox_publisher=_Publisher(),
            outbox_internal_handlers={},
            provider_event_handlers={},
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    "config_factory",
    [
        lambda: WorkerRuntimeConfig(max_concurrency=501),
        lambda: WorkerRuntimeConfig(idle_sleep=timedelta(0)),
    ],
)
def test_worker_runtime_rejects_unbounded_or_spin_configuration(
    config_factory: Callable[[], WorkerRuntimeConfig],
) -> None:
    with pytest.raises(ValueError):
        config_factory()
