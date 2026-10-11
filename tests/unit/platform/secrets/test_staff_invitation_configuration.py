import pytest

from request_engine.bootstrap.recovery_delivery import RecoveryDeliverySettings
from request_engine.bootstrap.staff_invitation_delivery import (
    build_staff_invitation_delivery,
    build_staff_invitation_staging,
)
from request_engine.platform.secrets.openbao_recovery_secret_store import OpenBaoRecoverySecretStore

pytestmark = [pytest.mark.unit]


def test_invitation_delivery_is_disabled_without_store_or_console_url() -> None:
    assert build_staff_invitation_delivery(RecoveryDeliverySettings.model_validate({})) is None
    assert (
        build_staff_invitation_delivery(
            RecoveryDeliverySettings.model_validate(
                {"staff_invitation_accept_url": "https://console.example.test/staff-invitations"}
            )
        )
        is None
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://remote.example.test/staff-invitations",
        "https://user:password@console.example.test/staff-invitations",
        "https://console.example.test/staff-invitations?next=https://evil.test",
        "https://console.example.test/staff-invitations#token=bad",
        "https://console.example.test/login",
    ],
)
def test_invitation_delivery_rejects_unsafe_console_urls(url: str) -> None:
    with pytest.raises(RuntimeError, match="trusted console"):
        build_staff_invitation_delivery(
            RecoveryDeliverySettings.model_validate({"staff_invitation_accept_url": url})
        )


def test_invitation_issuance_needs_store_not_bootstrap_smtp() -> None:
    settings = RecoveryDeliverySettings.model_validate(
        {
            "staff_invitation_accept_url": "https://console.example.test/staff-invitations",
            "openbao_addr": "https://secrets.example.test",
            "openbao_token": "test-only-provider-token",
        }
    )
    # Actual adapter composition, no credentials/read privileges for managed SMTP
    # in the application process. The worker resolves transport independently.
    staging = build_staff_invitation_staging(settings)
    assert isinstance(staging, OpenBaoRecoverySecretStore)
    assert build_staff_invitation_delivery(settings) is None


def test_invitation_staging_fails_closed_without_acceptance_url_or_store() -> None:
    assert build_staff_invitation_staging(RecoveryDeliverySettings.model_validate({})) is None
    assert (
        build_staff_invitation_staging(
            RecoveryDeliverySettings.model_validate(
                {"staff_invitation_accept_url": "https://console.example.test/staff-invitations"}
            )
        )
        is None
    )
