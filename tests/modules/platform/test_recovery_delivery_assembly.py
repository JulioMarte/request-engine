from typing import Any

import pytest

import request_engine.bootstrap.recovery_delivery as recovery_delivery
from request_engine.bootstrap.recovery_delivery import (
    RecoveryDeliverySettings,
    build_recovery_secret_delivery,
)
from request_engine.platform.secrets.composed_delivery import ComposedRecoverySecretDelivery
from request_engine.platform.secrets.smtp_delivery_channel import SmtpRecoveryDeliveryChannel
from request_engine.platform.secrets.vault_secret_store import VaultRecoverySecretStore

pytestmark = [pytest.mark.unit]

_VAULT_TOKEN = "vault-token-value"
_SMTP_PASSWORD = "smtp-password-value"

_ENV_KEYS = (
    "REQUEST_ENGINE_RECOVERY_DELIVERY_FACTORY",
    "REQUEST_ENGINE_RECOVERY_RESET_URL",
    "REQUEST_ENGINE_VAULT_ADDR",
    "REQUEST_ENGINE_VAULT_TOKEN",
    "REQUEST_ENGINE_VAULT_NAMESPACE",
    "REQUEST_ENGINE_VAULT_MOUNT",
    "REQUEST_ENGINE_VAULT_PATH_PREFIX",
    "REQUEST_ENGINE_VAULT_TIMEOUT_SECONDS",
    "REQUEST_ENGINE_SMTP_HOST",
    "REQUEST_ENGINE_SMTP_PORT",
    "REQUEST_ENGINE_SMTP_USERNAME",
    "REQUEST_ENGINE_SMTP_PASSWORD",
    "REQUEST_ENGINE_SMTP_SENDER",
    "REQUEST_ENGINE_SMTP_STARTTLS",
    "REQUEST_ENGINE_SMTP_SSL",
    "REQUEST_ENGINE_SMTP_TIMEOUT_SECONDS",
)


@pytest.fixture(autouse=True)
def clean_delivery_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


class _FakeDelivery:
    async def stage(self, **kwargs: object) -> None:
        del kwargs

    async def discard(self, **kwargs: object) -> None:
        del kwargs

    async def publish(self, **kwargs: object) -> None:
        del kwargs

    async def reconcile(self, **kwargs: object) -> None:
        del kwargs


class _FakeFactoryModule:
    def __init__(self, factory: object) -> None:
        self.build = factory


def _configure_vault(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REQUEST_ENGINE_VAULT_ADDR", "https://vault.internal:8200")
    monkeypatch.setenv("REQUEST_ENGINE_VAULT_TOKEN", _VAULT_TOKEN)


def _configure_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REQUEST_ENGINE_SMTP_HOST", "mail.internal")
    monkeypatch.setenv("REQUEST_ENGINE_SMTP_SENDER", "noreply@example.com")
    monkeypatch.setenv("REQUEST_ENGINE_SMTP_PASSWORD", _SMTP_PASSWORD)


def _internal(delivery: object, name: str) -> Any:
    return getattr(delivery, name)


def _patch_import_module(monkeypatch: pytest.MonkeyPatch, module: object) -> None:
    def _import(_name: str) -> object:
        return module

    monkeypatch.setattr(recovery_delivery.importlib, "import_module", _import)


def test_unconfigured_returns_none() -> None:
    assert build_recovery_secret_delivery(RecoveryDeliverySettings()) is None


def test_vault_and_smtp_build_composed_delivery(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_vault(monkeypatch)
    _configure_smtp(monkeypatch)

    delivery = build_recovery_secret_delivery(RecoveryDeliverySettings())

    assert isinstance(delivery, ComposedRecoverySecretDelivery)
    assert isinstance(_internal(delivery, "_store"), VaultRecoverySecretStore)
    assert isinstance(_internal(delivery, "_channel"), SmtpRecoveryDeliveryChannel)


@pytest.mark.parametrize("missing_side", ["vault", "smtp"])
def test_single_sided_configuration_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    missing_side: str,
) -> None:
    if missing_side == "vault":
        _configure_smtp(monkeypatch)
    else:
        _configure_vault(monkeypatch)

    with pytest.raises(RuntimeError, match="both Vault and SMTP"):
        build_recovery_secret_delivery(RecoveryDeliverySettings())


def test_partial_side_configuration_names_missing_keys_without_leaking_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_vault(monkeypatch)

    with pytest.raises(RuntimeError) as excinfo:
        build_recovery_secret_delivery(RecoveryDeliverySettings())

    message = str(excinfo.value)
    assert "REQUEST_ENGINE_SMTP_HOST" in message
    assert _VAULT_TOKEN not in message


def test_missing_required_key_names_it_without_leaking_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_vault(monkeypatch)
    monkeypatch.setenv("REQUEST_ENGINE_SMTP_HOST", "mail.internal")
    monkeypatch.setenv("REQUEST_ENGINE_SMTP_PASSWORD", _SMTP_PASSWORD)

    with pytest.raises(RuntimeError) as excinfo:
        build_recovery_secret_delivery(RecoveryDeliverySettings())

    message = str(excinfo.value)
    assert "REQUEST_ENGINE_SMTP_SENDER" in message
    assert _VAULT_TOKEN not in message
    assert _SMTP_PASSWORD not in message


def test_factory_override_returns_supplied_delivery(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_delivery = _FakeDelivery()
    monkeypatch.setenv("REQUEST_ENGINE_RECOVERY_DELIVERY_FACTORY", "fake.delivery:build")
    _patch_import_module(monkeypatch, _FakeFactoryModule(lambda: fake_delivery))

    delivery = build_recovery_secret_delivery(RecoveryDeliverySettings())

    assert delivery is fake_delivery


@pytest.mark.parametrize("factory_path", ["missing_separator", ":build", "fake.delivery:"])
def test_malformed_factory_path_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    factory_path: str,
) -> None:
    monkeypatch.setenv("REQUEST_ENGINE_RECOVERY_DELIVERY_FACTORY", factory_path)

    with pytest.raises(RuntimeError, match="module:factory"):
        build_recovery_secret_delivery(RecoveryDeliverySettings())


def test_non_callable_factory_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REQUEST_ENGINE_RECOVERY_DELIVERY_FACTORY", "fake.delivery:build")
    _patch_import_module(monkeypatch, _FakeFactoryModule(42))

    with pytest.raises(RuntimeError, match="not callable"):
        build_recovery_secret_delivery(RecoveryDeliverySettings())


def test_non_conforming_factory_result_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REQUEST_ENGINE_RECOVERY_DELIVERY_FACTORY", "fake.delivery:build")
    _patch_import_module(monkeypatch, _FakeFactoryModule(object))

    with pytest.raises(RuntimeError, match="stage, discard, publish and reconcile"):
        build_recovery_secret_delivery(RecoveryDeliverySettings())
