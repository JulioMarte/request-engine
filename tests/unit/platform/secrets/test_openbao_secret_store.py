from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from uuid import UUID

import httpx
import pytest

from request_engine.platform.secrets.openbao_secret_store import OpenBaoPlatformSecretStore
from request_engine.platform.secrets.platform_store import (
    PlatformSecretConflict,
    PlatformSecretNotFound,
    PlatformSecretStoreUnavailable,
)

pytestmark = [pytest.mark.unit]

_SECRET_ID = UUID("11111111-2222-3333-4444-555555555555")
_PATH = f"request-engine/platform/{_SECRET_ID}"
_VALUE = "platform-secret-sentinel"
_TOKEN = "short-lived-openbao-token"


def _store(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    token: str | None = _TOKEN,
) -> OpenBaoPlatformSecretStore:
    return OpenBaoPlatformSecretStore(
        address="https://openbao.test",
        token=token,
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.asyncio
async def test_create_uses_cas_zero_and_internal_uuid_path() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        assert request.headers["X-Vault-Token"] == _TOKEN
        return httpx.Response(200, json={"data": {"version": 1}})

    metadata = await _store(handler).write(
        secret_id=_SECRET_ID,
        value=_VALUE,
        expected_version=None,
    )

    assert seen["path"] == f"/v1/secret/data/{_PATH}"
    assert seen["body"] == {"data": {"value": _VALUE}, "options": {"cas": 0}}
    assert metadata.secret_id == _SECRET_ID
    assert metadata.version == 1


@pytest.mark.asyncio
async def test_rotation_requires_exact_version() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"data": {"version": 8}})

    metadata = await _store(handler).write(
        secret_id=_SECRET_ID,
        value="rotated",
        expected_version=7,
    )

    assert seen["body"]["options"] == {"cas": 7}
    assert metadata.version == 8


@pytest.mark.asyncio
async def test_stale_rotation_conflicts_instead_of_overwriting() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"errors": ["check-and-set parameter mismatch"]})

    with pytest.raises(PlatformSecretConflict):
        await _store(handler).write(
            secret_id=_SECRET_ID,
            value="stale",
            expected_version=3,
        )


@pytest.mark.asyncio
async def test_resolve_returns_runtime_plaintext_only() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/v1/secret/data/{_PATH}"
        return httpx.Response(
            200,
            json={"data": {"data": {"value": _VALUE}, "metadata": {"version": 2}}},
        )

    assert await _store(handler).resolve(secret_id=_SECRET_ID) == _VALUE


@pytest.mark.asyncio
async def test_metadata_never_returns_plaintext() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/v1/secret/metadata/{_PATH}"
        return httpx.Response(
            200,
            json={
                "data": {
                    "current_version": 4,
                    "updated_time": "2026-09-19T10:00:00Z",
                    "versions": {"4": {"created_time": "2026-09-19T09:00:00Z"}},
                }
            },
        )

    metadata = await _store(handler).metadata(secret_id=_SECRET_ID)

    assert metadata.secret_id == _SECRET_ID
    assert metadata.version == 4
    assert metadata.created_at is not None
    assert metadata.updated_at is not None
    assert not hasattr(metadata, "value")


@pytest.mark.asyncio
async def test_missing_secret_is_typed_not_found() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"errors": []})

    with pytest.raises(PlatformSecretNotFound):
        await _store(handler).resolve(secret_id=_SECRET_ID)


@pytest.mark.asyncio
async def test_agent_proxy_mode_does_not_require_static_token_header() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "X-Vault-Token" not in request.headers
        return httpx.Response(200, json={"data": {"data": {"value": _VALUE}}})

    assert await _store(handler, token=None).resolve(secret_id=_SECRET_ID) == _VALUE


@pytest.mark.asyncio
async def test_backend_error_never_contains_secret_or_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text=f"{_VALUE} {_TOKEN}")

    with pytest.raises(PlatformSecretStoreUnavailable) as excinfo:
        await _store(handler).write(
            secret_id=_SECRET_ID,
            value=_VALUE,
            expected_version=None,
        )

    message = str(excinfo.value)
    assert _VALUE not in message
    assert _TOKEN not in message
