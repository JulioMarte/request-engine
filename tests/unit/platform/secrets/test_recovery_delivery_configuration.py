from __future__ import annotations

import pytest

from request_engine.bootstrap.recovery_delivery import (
    RecoveryDeliverySettings,
    build_native_recovery_messenger,
    build_recovery_secret_delivery,
)
from request_engine.platform.secrets.composed_delivery import ComposedRecoverySecretDelivery
from request_engine.platform.secrets.smtp_delivery_channel import SmtpRecoveryDeliveryChannel

pytestmark = [pytest.mark.unit]


def _smtp_settings(**overrides: object) -> RecoveryDeliverySettings:
    values: dict[str, object] = {
        "smtp_host": "mail.internal",
        "smtp_port": 587,
        "smtp_sender": "recovery@example.test",
        "smtp_username": "recovery@example.test",
        "smtp_password": "smtp-password",
    }
    values.update(overrides)
    return RecoveryDeliverySettings.model_validate(values)


def test_openbao_proxy_mode_composes_without_static_openbao_token() -> None:
    delivery = build_recovery_secret_delivery(
        _smtp_settings(openbao_addr="http://openbao-proxy:8100")
    )

    assert isinstance(delivery, ComposedRecoverySecretDelivery)


def test_vault_remains_compatibility_backend() -> None:
    delivery = build_recovery_secret_delivery(
        _smtp_settings(
            vault_addr="http://vault:8200",
            vault_token="vault-token",
        )
    )

    assert isinstance(delivery, ComposedRecoverySecretDelivery)


def test_openbao_and_vault_together_fail_closed() -> None:
    with pytest.raises(RuntimeError, match="exactly one"):
        build_recovery_secret_delivery(
            _smtp_settings(
                openbao_addr="http://openbao-proxy:8100",
                vault_addr="http://vault:8200",
                vault_token="vault-token",
            )
        )


@pytest.mark.parametrize(
    "settings",
    [
        RecoveryDeliverySettings(openbao_addr="http://openbao-proxy:8100"),
        _smtp_settings(),
    ],
)
def test_partial_recovery_delivery_configuration_fails_closed(
    settings: RecoveryDeliverySettings,
) -> None:
    with pytest.raises(RuntimeError, match="requires a secret store and SMTP"):
        build_recovery_secret_delivery(settings)


def test_native_recovery_messenger_supports_smtp_without_authentication() -> None:
    messenger = build_native_recovery_messenger(
        RecoveryDeliverySettings(
            smtp_host="mailpit",
            smtp_port=1025,
            smtp_sender="recovery@example.test",
            smtp_starttls=False,
        )
    )

    assert isinstance(messenger, SmtpRecoveryDeliveryChannel)


@pytest.mark.parametrize(
    ("username", "password"),
    [
        ("recovery@example.test", None),
        (None, "smtp-password"),
    ],
)
def test_native_recovery_messenger_rejects_partial_smtp_authentication(
    username: str | None,
    password: str | None,
) -> None:
    with pytest.raises(RuntimeError, match="requires both"):
        build_native_recovery_messenger(
            RecoveryDeliverySettings(
                smtp_host="mail.internal",
                smtp_sender="recovery@example.test",
                smtp_username=username,
                smtp_password=password,
            )
        )
