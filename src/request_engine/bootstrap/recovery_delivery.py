"""Deployment composition for the governed identity-recovery delivery adapter.

The control plane and the delivery worker must agree on one real adapter. A
deployment either configures both the secret store and the delivery channel,
supplies a ``module:factory`` override, or recovery issuance stays fail-closed
(``503 recovery_delivery_unconfigured``). Secret values are never echoed in
configuration errors.
"""

import importlib
from typing import Any, cast

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from request_engine.platform.secrets.composed_delivery import ComposedRecoverySecretDelivery
from request_engine.platform.secrets.delivery import RecoverySecretDelivery
from request_engine.platform.secrets.delivery_parts import RecoveryDeliveryChannel
from request_engine.platform.secrets.openbao_recovery_secret_store import (
    OpenBaoRecoverySecretStore,
)
from request_engine.platform.secrets.smtp_delivery_channel import SmtpRecoveryDeliveryChannel
from request_engine.platform.secrets.vault_secret_store import VaultRecoverySecretStore

_FACTORY_ENV = "REQUEST_ENGINE_RECOVERY_DELIVERY_FACTORY"
_DELIVERY_ATTRIBUTES = ("stage", "discard", "publish", "reconcile")


class RecoveryDeliverySettings(BaseSettings):
    """Optional governed delivery configuration; absence keeps issuance fail-closed."""

    model_config = SettingsConfigDict(
        env_prefix="REQUEST_ENGINE_", extra="ignore", hide_input_in_errors=True
    )
    recovery_delivery_factory: str | None = None
    recovery_reset_url: str | None = None
    openbao_addr: str | None = None
    openbao_token: SecretStr | None = None
    openbao_namespace: str | None = None
    openbao_mount: str = "secret"
    openbao_path_prefix: str = "request-engine/identity-recovery"
    openbao_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    vault_addr: str | None = None
    vault_token: SecretStr | None = None
    vault_namespace: str | None = None
    vault_mount: str = "secret"
    vault_path_prefix: str = "request-engine/identity-recovery"
    vault_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_sender: str | None = None
    smtp_starttls: bool = True
    smtp_ssl: bool = False
    smtp_timeout_seconds: float = Field(default=10.0, gt=0, le=60)


def build_native_recovery_messenger(
    settings: RecoveryDeliverySettings | None = None,
) -> SmtpRecoveryDeliveryChannel | None:
    """Build the SMTP-only Native HUMAN recovery messenger.

    Verified-address recovery persists only one-way token digests in PostgreSQL,
    so it does not require OpenBao/Vault staging. Absence of SMTP disables this
    optional channel without affecting offline recovery codes.
    """

    resolved = settings or RecoveryDeliverySettings()
    host_configured = _has_text(resolved.smtp_host)
    sender_configured = _has_text(resolved.smtp_sender)
    username_configured = _has_text(resolved.smtp_username)
    password_configured = _has_secret(resolved.smtp_password)
    if not any((host_configured, sender_configured, username_configured, password_configured)):
        return None
    if not (host_configured and sender_configured):
        raise RuntimeError(
            "native recovery email requires REQUEST_ENGINE_SMTP_HOST and REQUEST_ENGINE_SMTP_SENDER"
        )
    if username_configured != password_configured:
        raise RuntimeError(
            "native recovery SMTP authentication requires both "
            "REQUEST_ENGINE_SMTP_USERNAME and REQUEST_ENGINE_SMTP_PASSWORD"
        )
    return SmtpRecoveryDeliveryChannel(
        host=_required_text("REQUEST_ENGINE_SMTP_HOST", resolved.smtp_host),
        port=resolved.smtp_port,
        sender=_required_text("REQUEST_ENGINE_SMTP_SENDER", resolved.smtp_sender),
        username=resolved.smtp_username,
        password=(
            resolved.smtp_password.get_secret_value()
            if password_configured and resolved.smtp_password is not None
            else None
        ),
        starttls=resolved.smtp_starttls,
        use_ssl=resolved.smtp_ssl,
        timeout_seconds=resolved.smtp_timeout_seconds,
        reset_url=resolved.recovery_reset_url,
    )


def build_recovery_secret_delivery(
    settings: RecoveryDeliverySettings | None = None,
    *,
    channel_override: RecoveryDeliveryChannel | None = None,
) -> RecoverySecretDelivery | None:
    """Resolve the deployment's delivery adapter, or ``None`` when unconfigured."""

    resolved = settings or RecoveryDeliverySettings()
    if resolved.recovery_delivery_factory is not None:
        if channel_override is not None:
            raise RuntimeError(
                "managed SMTP channel cannot be combined with "
                "REQUEST_ENGINE_RECOVERY_DELIVERY_FACTORY"
            )
        return _factory_delivery(resolved.recovery_delivery_factory)

    openbao_configured = _has_text(resolved.openbao_addr) or _has_secret(resolved.openbao_token)
    vault_configured = _has_text(resolved.vault_addr) or _has_secret(resolved.vault_token)
    if openbao_configured and vault_configured:
        raise RuntimeError("configure exactly one recovery secret-store backend: OpenBao or Vault")
    smtp_configured = (
        _has_text(resolved.smtp_host)
        or _has_text(resolved.smtp_sender)
        or _has_secret(resolved.smtp_password)
    )
    secret_store_configured = openbao_configured or vault_configured
    if not secret_store_configured and not smtp_configured and channel_override is None:
        return None
    if not secret_store_configured or (not smtp_configured and channel_override is None):
        missing = _missing_configuration(
            openbao_configured=openbao_configured,
            vault_configured=vault_configured,
            smtp_configured=smtp_configured,
        )
        raise RuntimeError(
            "identity recovery delivery requires a secret store and SMTP configuration; "
            "missing: " + ", ".join(missing)
        )

    if openbao_configured:
        store = OpenBaoRecoverySecretStore(
            address=_required_text("REQUEST_ENGINE_OPENBAO_ADDR", resolved.openbao_addr),
            token=(
                resolved.openbao_token.get_secret_value()
                if resolved.openbao_token is not None
                else None
            ),
            mount=resolved.openbao_mount,
            path_prefix=resolved.openbao_path_prefix,
            timeout_seconds=resolved.openbao_timeout_seconds,
            namespace=resolved.openbao_namespace,
        )
    else:
        store = VaultRecoverySecretStore(
            address=_required_text("REQUEST_ENGINE_VAULT_ADDR", resolved.vault_addr),
            token=_required_secret("REQUEST_ENGINE_VAULT_TOKEN", resolved.vault_token),
            mount=resolved.vault_mount,
            path_prefix=resolved.vault_path_prefix,
            timeout_seconds=resolved.vault_timeout_seconds,
            namespace=resolved.vault_namespace,
        )
    channel = channel_override
    if channel is None:
        channel = SmtpRecoveryDeliveryChannel(
            host=_required_text("REQUEST_ENGINE_SMTP_HOST", resolved.smtp_host),
            port=resolved.smtp_port,
            sender=_required_text("REQUEST_ENGINE_SMTP_SENDER", resolved.smtp_sender),
            username=resolved.smtp_username,
            password=(
                resolved.smtp_password.get_secret_value()
                if resolved.smtp_password is not None
                else None
            ),
            starttls=resolved.smtp_starttls,
            use_ssl=resolved.smtp_ssl,
            timeout_seconds=resolved.smtp_timeout_seconds,
            reset_url=resolved.recovery_reset_url,
        )
    return ComposedRecoverySecretDelivery(store=store, channel=channel)


def has_recovery_secret_store_configuration(
    settings: RecoveryDeliverySettings,
) -> bool:
    return (
        _has_text(settings.openbao_addr)
        or _has_secret(settings.openbao_token)
        or _has_text(settings.vault_addr)
        or _has_secret(settings.vault_token)
    )


def _has_text(value: str | None) -> bool:
    return value is not None and bool(value.strip())


def _has_secret(value: SecretStr | None) -> bool:
    return value is not None and bool(value.get_secret_value().strip())


def _missing_configuration(
    *,
    openbao_configured: bool,
    vault_configured: bool,
    smtp_configured: bool,
) -> tuple[str, ...]:
    missing: list[str] = []
    if not openbao_configured and not vault_configured:
        missing.append("REQUEST_ENGINE_OPENBAO_ADDR (preferred) or REQUEST_ENGINE_VAULT_ADDR/TOKEN")
    if not smtp_configured:
        missing.extend(
            (
                "REQUEST_ENGINE_SMTP_HOST",
                "REQUEST_ENGINE_SMTP_SENDER",
                "REQUEST_ENGINE_SMTP_PASSWORD",
            )
        )
    return tuple(missing)


def _required_text(name: str, value: str | None) -> str:
    if value is None or not value.strip():
        raise RuntimeError(f"{name} is required when identity recovery delivery is configured")
    return value


def _required_secret(name: str, value: SecretStr | None) -> str:
    if value is None or not value.get_secret_value().strip():
        raise RuntimeError(f"{name} is required when identity recovery delivery is configured")
    return value.get_secret_value()


def _factory_delivery(factory_path: str) -> RecoverySecretDelivery:
    module_name, separator, attribute_name = factory_path.partition(":")
    if not separator or not module_name or not attribute_name:
        raise RuntimeError(f"{_FACTORY_ENV} must use the form module:factory")
    factory: Any = getattr(importlib.import_module(module_name), attribute_name, None)
    if not callable(factory):
        raise RuntimeError(f"{_FACTORY_ENV} {factory_path!r} is not callable")
    delivery: Any = factory()
    for attribute in _DELIVERY_ATTRIBUTES:
        if not callable(getattr(delivery, attribute, None)):
            raise RuntimeError(
                f"{_FACTORY_ENV} result must implement callable "
                "stage, discard, publish and reconcile"
            )
    return cast(RecoverySecretDelivery, delivery)
