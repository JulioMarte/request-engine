from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest

from request_engine.platform.secrets.delivery import RecoveryDeliveryPermanent
from request_engine.platform.secrets.openbao_recovery_secret_store import (
    OpenBaoRecoverySecretStore,
)

pytestmark = [pytest.mark.unit]

_CASE_ID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
_SECRET = "offline-delivery-proof"
_DIGEST = hashlib.sha256(_SECRET.encode()).hexdigest()
_PATH = f"request-engine/identity-recovery/{_CASE_ID}/1"


def _store(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    token: str | None = None,
) -> OpenBaoRecoverySecretStore:
    return OpenBaoRecoverySecretStore(
        address="http://openbao-agent.test:8100",
        token=token,
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.asyncio
async def test_agent_mode_stages_with_cas_and_no_static_token() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert "X-Vault-Token" not in request.headers
        if "/metadata/" in request.url.path:
            seen["metadata"] = json.loads(request.content)
            return httpx.Response(200, json={})
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"data": {"version": 1}})

    expires_at = datetime.now(UTC) + timedelta(minutes=30)
    staged = await _store(handler).stage(
        case_id=_CASE_ID,
        generation=1,
        secret=_SECRET,
        expires_at=expires_at,
    )

    assert seen["body"]["options"] == {"cas": 0}
    assert seen["body"]["data"]["secret"] == _SECRET
    assert staged.reference == _PATH
    assert staged.digest == _DIGEST
    assert staged.created is True


@pytest.mark.asyncio
async def test_read_rejects_reference_outside_configured_prefix() -> None:
    with pytest.raises(RecoveryDeliveryPermanent, match="outside OpenBao scope"):
        await _store(lambda _: httpx.Response(500)).read(reference="other-tenant/secret")


@pytest.mark.asyncio
async def test_cas_replay_reads_original_winner() -> None:
    expires_at = datetime.now(UTC) + timedelta(minutes=20)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(400, json={"errors": ["cas mismatch"]})
        return httpx.Response(
            200,
            json={
                "data": {
                    "data": {
                        "secret": "winner",
                        "digest": "a" * 64,
                        "expires_at": expires_at.isoformat(),
                    }
                }
            },
        )

    staged = await _store(handler).stage(
        case_id=_CASE_ID,
        generation=1,
        secret=_SECRET,
        expires_at=expires_at,
    )

    assert staged.created is False
    assert staged.digest == "a" * 64
    assert staged.reference == _PATH
