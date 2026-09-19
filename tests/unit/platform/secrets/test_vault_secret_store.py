import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest

from request_engine.platform.secrets.delivery import (
    RecoveryDeliveryPermanent,
    RecoveryDeliveryRetryable,
)
from request_engine.platform.secrets.vault_secret_store import VaultRecoverySecretStore

pytestmark = [pytest.mark.unit]

_CASE_ID = UUID("11111111-1111-1111-1111-111111111111")
_PATH = f"request-engine/identity-recovery/{_CASE_ID}/1"
_SECRET = "raw-recovery-proof-value"
_TOKEN = "vault-token-sentinel-do-not-leak"
_DIGEST = hashlib.sha256(_SECRET.encode("utf-8")).hexdigest()


def _store(handler: Callable[[httpx.Request], httpx.Response]) -> VaultRecoverySecretStore:
    return VaultRecoverySecretStore(
        address="https://vault.test",
        token=_TOKEN,
        transport=httpx.MockTransport(handler),
    )


def _expires_at() -> datetime:
    return datetime.now(UTC) + timedelta(minutes=30)


@pytest.mark.asyncio
async def test_stage_creates_if_absent_with_cas_zero() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Vault-Token"] == _TOKEN
        if request.url.path.startswith("/v1/secret/metadata/"):
            seen["ttl_path"] = request.url.path
            seen["ttl_body"] = json.loads(request.content)
            return httpx.Response(200, json={})
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"data": {"version": 1}})

    expires_at = _expires_at()
    staged = await _store(handler).stage(
        case_id=_CASE_ID,
        generation=1,
        secret=_SECRET,
        expires_at=expires_at,
    )

    assert seen["path"] == f"/v1/secret/data/{_PATH}"
    assert seen["body"]["options"] == {"cas": 0}
    assert seen["body"]["data"]["secret"] == _SECRET
    assert seen["body"]["data"]["digest"] == _DIGEST
    assert seen["body"]["data"]["expires_at"] == expires_at.isoformat()
    assert seen["ttl_path"] == f"/v1/secret/metadata/{_PATH}"
    assert seen["ttl_body"]["delete_version_after"].endswith("s")
    assert staged.created is True
    assert staged.reference == _PATH
    assert staged.digest == _DIGEST
    assert staged.expires_at == expires_at


@pytest.mark.asyncio
async def test_stage_cas_conflict_returns_existing_without_created() -> None:
    existing_digest = "b" * 64
    existing_expires_at = datetime.now(UTC) + timedelta(minutes=10)
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.method == "POST":
            return httpx.Response(
                400,
                json={"errors": ["check-and-set parameter required for this operation"]},
            )
        return httpx.Response(
            200,
            json={
                "data": {
                    "data": {
                        "secret": "winner-secret",
                        "digest": existing_digest,
                        "expires_at": existing_expires_at.isoformat(),
                    }
                }
            },
        )

    staged = await _store(handler).stage(
        case_id=_CASE_ID,
        generation=1,
        secret=_SECRET,
        expires_at=_expires_at(),
    )

    assert staged.created is False
    assert staged.reference == _PATH
    assert staged.digest == existing_digest
    assert staged.expires_at == existing_expires_at
    assert calls == [
        f"POST /v1/secret/data/{_PATH}",
        f"GET /v1/secret/data/{_PATH}",
    ]


@pytest.mark.asyncio
async def test_stage_cas_conflict_without_existing_is_retryable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(400, json={"errors": ["cas mismatch"]})
        return httpx.Response(404, json={"errors": []})

    with pytest.raises(RecoveryDeliveryRetryable):
        await _store(handler).stage(
            case_id=_CASE_ID,
            generation=1,
            secret=_SECRET,
            expires_at=_expires_at(),
        )


@pytest.mark.asyncio
async def test_stage_server_error_is_retryable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"errors": ["standby"]})

    with pytest.raises(RecoveryDeliveryRetryable):
        await _store(handler).stage(
            case_id=_CASE_ID,
            generation=1,
            secret=_SECRET,
            expires_at=_expires_at(),
        )


@pytest.mark.asyncio
async def test_stage_client_error_is_permanent() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"errors": ["permission denied"]})

    with pytest.raises(RecoveryDeliveryPermanent):
        await _store(handler).stage(
            case_id=_CASE_ID,
            generation=1,
            secret=_SECRET,
            expires_at=_expires_at(),
        )


@pytest.mark.asyncio
async def test_discard_issues_metadata_delete() -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        return httpx.Response(204)

    await _store(handler).discard(case_id=_CASE_ID, generation=1)

    assert calls == [("DELETE", f"/v1/secret/metadata/{_PATH}")]


@pytest.mark.asyncio
async def test_discard_ignores_missing_secret() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"errors": []})

    await _store(handler).discard(case_id=_CASE_ID, generation=1)


@pytest.mark.asyncio
async def test_discard_server_error_is_retryable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"errors": ["boom"]})

    with pytest.raises(RecoveryDeliveryRetryable):
        await _store(handler).discard(case_id=_CASE_ID, generation=1)


@pytest.mark.asyncio
async def test_read_returns_raw_secret() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/v1/secret/data/{_PATH}"
        return httpx.Response(
            200,
            json={
                "data": {
                    "data": {
                        "secret": _SECRET,
                        "digest": _DIGEST,
                        "expires_at": _expires_at().isoformat(),
                    }
                }
            },
        )

    assert await _store(handler).read(reference=_PATH) == _SECRET


@pytest.mark.asyncio
async def test_read_missing_secret_is_permanent() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"errors": []})

    with pytest.raises(RecoveryDeliveryPermanent, match="unavailable"):
        await _store(handler).read(reference=_PATH)


@pytest.mark.asyncio
async def test_read_server_error_is_retryable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"errors": ["boom"]})

    with pytest.raises(RecoveryDeliveryRetryable):
        await _store(handler).read(reference=_PATH)


@pytest.mark.asyncio
async def test_read_expired_secret_is_permanent() -> None:
    expired_at = datetime.now(UTC) - timedelta(seconds=1)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "data": {
                        "secret": _SECRET,
                        "digest": _DIGEST,
                        "expires_at": expired_at.isoformat(),
                    }
                }
            },
        )

    with pytest.raises(RecoveryDeliveryPermanent, match="expired"):
        await _store(handler).read(reference=_PATH)


@pytest.mark.asyncio
async def test_read_malformed_success_body_is_permanent() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"data": {}}})

    with pytest.raises(RecoveryDeliveryPermanent, match="malformed"):
        await _store(handler).read(reference=_PATH)


@pytest.mark.asyncio
async def test_vault_credentials_never_appear_in_raised_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal server error")

    with pytest.raises(RecoveryDeliveryRetryable) as excinfo:
        await _store(handler).stage(
            case_id=_CASE_ID,
            generation=1,
            secret=_SECRET,
            expires_at=_expires_at(),
        )

    message = str(excinfo.value)
    assert _SECRET not in message
    assert _TOKEN not in message
