"""Effective first-version TTL, failed metadata and retained-winner safety."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest

from request_engine.platform.secrets.delivery import (
    RecoveryDeliveryPermanent,
    RecoveryDeliveryRetryable,
)
from request_engine.platform.secrets.openbao_recovery_secret_store import OpenBaoRecoverySecretStore
from request_engine.platform.secrets.vault_secret_store import VaultRecoverySecretStore

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", [VaultRecoverySecretStore, OpenBaoRecoverySecretStore])
@pytest.mark.parametrize("failure", [403, 429, 503, "transport"])
async def test_metadata_failure_aborts_before_data_and_is_safely_observable(
    provider: type[VaultRecoverySecretStore] | type[OpenBaoRecoverySecretStore],
    failure: int | str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if failure == "transport":
            raise httpx.ConnectError("secret-token-sentinel", request=request)
        return httpx.Response(int(failure), text="secret-token-sentinel")

    store = provider(
        address="https://secret.test",
        token="secret-token-sentinel",
        transport=httpx.MockTransport(handler),
    )
    error = RecoveryDeliveryPermanent if failure == 403 else RecoveryDeliveryRetryable
    with pytest.raises(error) as caught:
        await store.stage(
            case_id=uuid4(),
            generation=1,
            secret="proof-sentinel",
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
        )
    assert len(calls) == 1 and "/metadata/" in calls[0]
    assert "secret_retention_metadata" in caplog.text
    assert "secret-token-sentinel" not in str(caught.value) + caplog.text
    assert "proof-sentinel" not in str(caught.value) + caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", [VaultRecoverySecretStore, OpenBaoRecoverySecretStore])
@pytest.mark.parametrize("retained", [False, True])
@pytest.mark.parametrize("deadline", [None, "", "malformed", "past", "late"])
async def test_unverified_retention_never_returns_success_or_deletes_retained_candidate(
    provider: type[VaultRecoverySecretStore] | type[OpenBaoRecoverySecretStore],
    retained: bool,
    deadline: str | None,
) -> None:
    expiry = datetime.now(UTC) + timedelta(minutes=10)
    deletion_time = {
        "past": datetime.now(UTC) - timedelta(seconds=1),
        "late": expiry + timedelta(hours=1),
    }.get(deadline or "")
    value = deletion_time.isoformat() if deletion_time else deadline
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if "/metadata/" in request.url.path:
            return httpx.Response(204)
        if request.method == "POST":
            if retained:
                return httpx.Response(400, json={"errors": ["cas mismatch"]})
            return httpx.Response(200, json={"data": {"version": 1, "deletion_time": value}})
        return httpx.Response(
            200,
            json={
                "data": {
                    "metadata": {"deletion_time": value},
                    "data": {
                        "secret": "retained-winner",
                        "digest": "b" * 64,
                        "expires_at": expiry.isoformat(),
                    },
                }
            },
        )

    store = provider(
        address="https://secret.test", token="test", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(RecoveryDeliveryPermanent, match="retention deadline unverified"):
        await store.stage(case_id=uuid4(), generation=1, secret="loser-proof", expires_at=expiry)
    assert calls[0][0] == "POST" and "/metadata/" in calls[0][1]
    assert not any(method == "DELETE" or "/destroy/" in path for method, path in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", [VaultRecoverySecretStore, OpenBaoRecoverySecretStore])
async def test_expired_or_too_short_deadline_never_disables_retention(
    provider: type[VaultRecoverySecretStore] | type[OpenBaoRecoverySecretStore],
) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(204)

    store = provider(
        address="https://secret.test", token="test", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(RecoveryDeliveryPermanent, match="too short"):
        await store.stage(
            case_id=uuid4(),
            generation=1,
            secret="proof",
            expires_at=datetime.now(UTC) + timedelta(milliseconds=100),
        )
    assert calls == []
