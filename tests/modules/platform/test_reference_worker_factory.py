import sys
from collections.abc import Callable, Mapping
from types import ModuleType
from typing import cast
from uuid import uuid4

import pytest

from request_engine.bootstrap import reference_worker_factory
from request_engine.bootstrap import worker as worker_bootstrap
from request_engine.entrypoints.worker.outbox_runtime import (
    RESERVATION_LIFECYCLE_EVENT_TYPES,
    ReservationLifecycleOutboxHandler,
)
from request_engine.platform.db.session import SessionFactory

PUBLISHER_MODULE = "reference_publisher_deployment"


class _ReminderCommandsDouble:
    def materialize(self, lease: object) -> None:
        del lease


class _CapturedPipeline:
    def __init__(
        self,
        *,
        fenced_internal_handlers: Mapping[str, Callable[..., object]],
        **kwargs: object,
    ) -> None:
        del kwargs
        self.fenced = fenced_internal_handlers


class _PublisherDouble:
    async def publish(self, event: object) -> None:
        del event


def _configure_reference_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REQUEST_ENGINE_WEBHOOK_BASE_URL", "https://transport.example.test/handoff")
    monkeypatch.setenv("REQUEST_ENGINE_WEBHOOK_AUTH_HEADER", "Authorization: Bearer reference-1")
    monkeypatch.setenv(
        "REQUEST_ENGINE_WORKER_DATABASE_URL", "postgresql+asyncpg://worker@db/reference"
    )
    monkeypatch.setenv("REQUEST_ENGINE_APP_DATABASE_URL", "postgresql+asyncpg://app@db/reference")
    monkeypatch.setenv("REQUEST_ENGINE_WORKER_PRINCIPAL_ID", str(uuid4()))
    module = ModuleType(PUBLISHER_MODULE)
    module.create_publisher = lambda: _PublisherDouble()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setenv(
        "REQUEST_ENGINE_OUTBOX_PUBLISHER_FACTORY", f"{PUBLISHER_MODULE}:create_publisher"
    )


def _record_adapter(recorded: dict[str, SessionFactory], name: str) -> Callable[..., object]:
    def capture(*arguments: object, **keywords: object) -> object:
        del keywords
        recorded[name] = cast(SessionFactory, arguments[0])
        return object()

    return capture


@pytest.mark.unit
def test_reference_factory_composes_reservation_lifecycle_handlers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_reference_environment(monkeypatch)
    pipelines: list[_CapturedPipeline] = []
    worker_factories: list[SessionFactory] = []
    domain_factories: list[SessionFactory] = []
    adapter_factories: dict[str, SessionFactory] = {}

    def capture_pipeline(**kwargs: object) -> _CapturedPipeline:
        pipeline = _CapturedPipeline(
            fenced_internal_handlers=cast(
                Mapping[str, Callable[..., object]],
                kwargs["fenced_internal_handlers"],
            ),
        )
        pipelines.append(pipeline)
        return pipeline

    def capture_outbox_store(factory: SessionFactory) -> object:
        worker_factories.append(factory)
        return object()

    def capture_reminder_commands(factory: SessionFactory) -> _ReminderCommandsDouble:
        domain_factories.append(factory)
        return _ReminderCommandsDouble()

    monkeypatch.setattr(worker_bootstrap, "OutboxPipelineProcessor", capture_pipeline)
    monkeypatch.setattr(worker_bootstrap, "PostgresOutboxWorker", capture_outbox_store)
    monkeypatch.setattr(
        worker_bootstrap, "PostgresReminderOccurrenceCommands", capture_reminder_commands
    )
    adapter_names = (
        "PostgresReservationLifecycleReader",
        "PostgresReservationLifecycleScheduling",
        "PostgresReservationLifecycleNotificationIntent",
        "PostgresReleasedSlotRecovery",
    )
    for name in adapter_names:
        monkeypatch.setattr(
            reference_worker_factory, name, _record_adapter(adapter_factories, name)
        )

    reference_worker_factory.create_worker()

    fenced = pipelines[0].fenced
    assert set(fenced) == set(RESERVATION_LIFECYCLE_EVENT_TYPES)
    assert all(
        isinstance(getattr(handler, "__self__", None), ReservationLifecycleOutboxHandler)
        for handler in fenced.values()
    )
    assert set(adapter_factories) == set(adapter_names)
    assert set(adapter_factories.values()) == {domain_factories[0]}
    assert domain_factories[0] is not worker_factories[0]
