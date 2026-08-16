from typing import cast

import pytest

from request_engine.bootstrap import worker as worker_bootstrap
from request_engine.entrypoints.worker.outbox_runtime import (
    OutboxEvent,
    ReservationLifecycleOutboxHandler,
)
from request_engine.modules.booking.adapters.worker.no_show import NoShowScheduledHandler
from request_engine.modules.queue.adapters.worker.slot_offer_expiry import (
    SlotOfferExpiryScheduledHandler,
)
from request_engine.platform.db.session import SessionFactory


class _Publisher:
    async def publish(self, event: OutboxEvent) -> None:
        del event


class _ScheduledHandler:
    async def handle(self, lease: object) -> None:
        del lease


class _LifecycleHandler:
    def handlers(self) -> dict[str, object]:
        return {}


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


def _worker_store(factory: SessionFactory) -> object:
    del factory
    return object()


def _provider_store(factory: SessionFactory) -> _ProviderStore:
    del factory
    return _ProviderStore()


@pytest.mark.unit
def test_reservation_lifecycle_factory_receives_only_domain_session_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker_factory = cast(SessionFactory, object())
    domain_factory = cast(SessionFactory, object())
    lifecycle_factories_seen: list[SessionFactory] = []

    monkeypatch.setattr(worker_bootstrap, "PostgresScheduledActionWorker", _worker_store)
    monkeypatch.setattr(worker_bootstrap, "PostgresOutboxWorker", _worker_store)
    monkeypatch.setattr(worker_bootstrap, "PostgresProviderEventWorker", _provider_store)
    monkeypatch.setattr(worker_bootstrap, "FencedWorkerRuntime", _CapturedRuntime)

    def lifecycle_factory(factory: SessionFactory) -> ReservationLifecycleOutboxHandler:
        lifecycle_factories_seen.append(factory)
        return cast(ReservationLifecycleOutboxHandler, _LifecycleHandler())

    worker_bootstrap.build_worker_process(
        worker_session_factory=worker_factory,
        domain_session_factory=domain_factory,
        no_show_factory=lambda _: cast(NoShowScheduledHandler, _ScheduledHandler()),
        slot_offer_expiry_factory=lambda _: cast(
            SlotOfferExpiryScheduledHandler, _ScheduledHandler()
        ),
        communication_providers={},
        outbox_publisher=_Publisher(),
        outbox_internal_handlers={},
        provider_event_handlers={},
        reservation_lifecycle_factory=lifecycle_factory,
    )

    assert lifecycle_factories_seen == [domain_factory]


@pytest.mark.unit
def test_production_assembly_rejects_generic_reservation_lifecycle_handler() -> None:
    worker_factory = cast(SessionFactory, object())
    domain_factory = cast(SessionFactory, object())

    async def bypass(event: OutboxEvent) -> None:
        del event

    with pytest.raises(ValueError, match="reservation_lifecycle_factory"):
        worker_bootstrap.build_worker_process(
            worker_session_factory=worker_factory,
            domain_session_factory=domain_factory,
            no_show_factory=lambda _: cast(NoShowScheduledHandler, _ScheduledHandler()),
            slot_offer_expiry_factory=lambda _: cast(
                SlotOfferExpiryScheduledHandler, _ScheduledHandler()
            ),
            communication_providers={},
            outbox_publisher=_Publisher(),
            outbox_internal_handlers={"reservation.created.v1": bypass},
            provider_event_handlers={},
        )
