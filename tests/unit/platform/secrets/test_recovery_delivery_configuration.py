from __future__ import annotations

import pytest

from request_engine.bootstrap.recovery_delivery import (
    RecoveryDeliverySettings,
    build_recovery_secret_delivery,
)
from request_engine.platform.secrets.composed_delivery import ComposedRecoverySecretDelivery
from request_engine.platform.secrets.openbao_recovery_secret_store import (
    OpenBaoRecoverySecretStore,
)
from request_engine.platform.secrets.vault_secret_store import VaultRecoverySecretStore

pytestmark = [pytest.mark.unit]


def _smtp() -> dict[str, object]:
    return {
        "smtp_host": "mail.internal",
        "smtp_port": 587,
        "smtp_sender": "recovery@example.test",
        "smtp_username": "recovery@example.test",
        "smtp_password": "smtp-password",
    }


def test_openbao_proxy_mode_composes_without_static_openbao_token() -> None:
    delivery = build_recovery_secret_delivery(
        RecoveryDeliverySettings(
            openbao_addr="http://openbao-proxy:8100",
            **_smtp(),
        )
    )

    assert isinstance(delivery, ComposedRecoverySecretDelivery)
    assert isinstance(delivery._store, OpenBaoRecoverySecretStore)  # noqa: SLF001


def test_vault_remains_compatibility_backend() -> None:
    delivery = build_recovery_secret_delivery(
        RecoveryDeliverySettings(
            vault_addr="http://vault:8200",
            vault_token="vault-token",
            **_smtp(),
        )
    )

    assert isinstance(delivery, ComposedRecoverySecretDelivery)
    assert isinstance(delivery._store, VaultRecoverySecretStore)  # noqa: SLF001


def test_openbao_and_vault_together_fail_closed() -> None:
    with pytest.raises(RuntimeError, match="exactly one"):
        build_recovery_secret_delivery(
            RecoveryDeliverySettings(
                openbao_addr="http://openbao-proxy:8100",
                vault_addr="http://vault:8200",
                vault_token="vault-token",
                **_smtp(),
            )
        )


@pytest.mark.parametrize(
    "settings",
    [
        RecoveryDeliverySettings(openbao_addr="http://openbao-proxy:8100"),
        RecoveryDeliverySettings(**_smtp()),
    ],
)
def test_partial_recovery_delivery_configuration_fails_closed(
    settings: RecoveryDeliverySettings,
) -> None:
    with pytest.raises(RuntimeError, match="requires a secret store and SMTP"):
        build_recovery_secret_delivery(settings)
