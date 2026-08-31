import sys
from collections.abc import Mapping
from types import ModuleType
from uuid import uuid4

import pytest

from request_engine.bootstrap import worker as worker_bootstrap
from request_engine.bootstrap.reference_worker_factory import create_worker
from request_engine.entrypoints.worker.app import WorkerProcess
from request_engine.entrypoints.worker.cli import load_worker_process
from request_engine.modules.communications.adapters.transport.webhook_delivery_provider import (
    WEBHOOK_PROVIDER_KEY,
    WebhookDeliveryProvider,
)

PUBLISHER_MODULE = "reference_publisher_deployment"
CANONICAL_STREAM_NAMES = (
    "scheduled_actions",
    "outbox_messages",
    "provider_events",
    "recovery_sweep",
)


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


class _DeliveryHandlerDouble:
    async def handle(self, lease: object) -> None:
        del lease


def _capture_delivery_handler(
    monkeypatch: pytest.MonkeyPatch,
    captured: list[Mapping[str, object]],
) -> None:
    def capture(
        session_factory: object,
        scheduler: object,
        providers: Mapping[str, object],
    ) -> _DeliveryHandlerDouble:
        del session_factory, scheduler
        captured.append(providers)
        return _DeliveryHandlerDouble()

    monkeypatch.setattr(worker_bootstrap, "CommunicationDeliveryScheduledHandler", capture)


def _assert_webhook_provider_registered(captured: list[Mapping[str, object]]) -> None:
    assert set(captured[0]) == {WEBHOOK_PROVIDER_KEY}
    assert isinstance(captured[0][WEBHOOK_PROVIDER_KEY], WebhookDeliveryProvider)


@pytest.mark.unit
def test_reference_factory_composes_webhook_provider_into_production_assembly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_reference_environment(monkeypatch)
    captured: list[Mapping[str, object]] = []
    _capture_delivery_handler(monkeypatch, captured)

    process = create_worker()

    _assert_webhook_provider_registered(captured)
    assert process.stream_names == CANONICAL_STREAM_NAMES


@pytest.mark.unit
def test_worker_launcher_loads_the_reference_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_reference_environment(monkeypatch)
    captured: list[Mapping[str, object]] = []
    _capture_delivery_handler(monkeypatch, captured)

    process = load_worker_process("request_engine.bootstrap.reference_worker_factory:create_worker")

    assert isinstance(process, WorkerProcess)
    _assert_webhook_provider_registered(captured)
    assert process.stream_names == CANONICAL_STREAM_NAMES


@pytest.mark.unit
@pytest.mark.parametrize(
    "missing_setting",
    ["REQUEST_ENGINE_WEBHOOK_BASE_URL", "REQUEST_ENGINE_OUTBOX_PUBLISHER_FACTORY"],
)
def test_reference_factory_fails_loudly_when_required_setting_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    missing_setting: str,
) -> None:
    _configure_reference_environment(monkeypatch)
    monkeypatch.delenv(missing_setting)

    with pytest.raises(RuntimeError, match=missing_setting):
        create_worker()


@pytest.mark.unit
@pytest.mark.parametrize(
    ("setting_name", "invalid_value"),
    [
        ("REQUEST_ENGINE_WEBHOOK_AUTH_HEADER", "BearerTokenWithoutSeparator"),
        ("REQUEST_ENGINE_OUTBOX_PUBLISHER_FACTORY", f"{PUBLISHER_MODULE}:missing_publisher"),
    ],
)
def test_reference_factory_rejects_malformed_setting(
    monkeypatch: pytest.MonkeyPatch,
    setting_name: str,
    invalid_value: str,
) -> None:
    _configure_reference_environment(monkeypatch)
    monkeypatch.setenv(setting_name, invalid_value)

    with pytest.raises(RuntimeError, match=setting_name):
        create_worker()
