"""Temporary bearer proof stores cannot escape their closed namespace."""

from uuid import uuid4

import httpx
import pytest

from request_engine.platform.secrets.delivery import RecoveryDeliveryPermanent
from request_engine.platform.secrets.openbao_recovery_secret_store import OpenBaoRecoverySecretStore
from request_engine.platform.secrets.vault_secret_store import VaultRecoverySecretStore

pytestmark = [pytest.mark.unit, pytest.mark.security]


@pytest.mark.parametrize("store_type", [VaultRecoverySecretStore, OpenBaoRecoverySecretStore])
@pytest.mark.parametrize(
    "prefix", ["request-engine/platform", "other", "request-engine/identity-recovery/"]
)
def test_other_namespaces_rejected(store_type: type, prefix: str) -> None:
    with pytest.raises(ValueError):
        store_type(address="http://provider.test", token="test", path_prefix=prefix)


@pytest.mark.asyncio
@pytest.mark.parametrize("store_type", [VaultRecoverySecretStore, OpenBaoRecoverySecretStore])
@pytest.mark.parametrize(
    "suffix", ["../platform/secret", "1?version=2", "01", "0", "-1", "1/../2", "1#x"]
)
async def test_reference_rejected_before_provider_io(store_type: type, suffix: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("unsafe references must never reach the provider")

    store = store_type(
        address="http://provider.test", token="test", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(RecoveryDeliveryPermanent):
        await store.read(reference=f"request-engine/identity-recovery/{uuid4()}/{suffix}")


@pytest.mark.asyncio
@pytest.mark.parametrize("store_type", [VaultRecoverySecretStore, OpenBaoRecoverySecretStore])
@pytest.mark.parametrize("generation", [0, -1, True])
async def test_invalid_generation_rejected_without_io(store_type: type, generation: int) -> None:
    store = store_type(address="http://provider.test", token="test")
    with pytest.raises(ValueError):
        await store.discard(case_id=uuid4(), generation=generation)
