"""Real setup HTTP/service validation; the store observes admission, not DB semantics."""

from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI

from request_engine.entrypoints.http.instance_setup import install_instance_setup_http
from request_engine.platform.security.instance_setup import (
    InstanceSetupService,
    InstanceSetupStore,
    SetupSessionSnapshot,
)
from request_engine.platform.security.native_auth import issue_opaque_token
from request_engine.platform.security.native_webauthn_auth import NativeWebAuthnAuthService
from request_engine.platform.security.recovery_codes import NativeRecoveryCodeService


@pytest.mark.asyncio
@pytest.mark.parametrize("password", ["short", "é" * 600], ids=["too-short", "too-many-utf8-bytes"])
async def test_setup_password_rejection_is_422_before_pending_write(password: str) -> None:
    token = issue_opaque_token()
    snapshot = SetupSessionSnapshot(
        setup_session_id=token.token_id,
        status="active",
        is_usable=True,
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
        instance_state="unclaimed",
    )
    store_double = Mock(spec=InstanceSetupStore)
    read_session = AsyncMock(return_value=snapshot)
    pending_write = AsyncMock(return_value=True)
    store_double.read_setup_session = read_session
    store_double.set_pending_identity = pending_write
    service = InstanceSetupService(
        store=cast(InstanceSetupStore, store_double),
        webauthn=cast(NativeWebAuthnAuthService, Mock(spec=NativeWebAuthnAuthService)),
        recovery_codes=cast(NativeRecoveryCodeService, Mock(spec=NativeRecoveryCodeService)),
    )
    app = FastAPI()
    install_instance_setup_http(app, service=service)
    headers = {"Authorization": f"Setup {token.raw_token}"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        rejected = await client.post(
            "/v1/setup/native-identity",
            headers=headers,
            json={"login_handle": "owner@example.test", "password": password},
        )
        assert rejected.status_code == 422
        error = rejected.json()["error"]
        assert error["code"] == "password_policy_violation"
        assert error["retryable"] is False
        assert "at least 12 characters" in error["message"]
        assert "at most 1024 bytes" in error["message"]
        assert rejected.headers["cache-control"] == "no-store"
        assert password not in rejected.text
        read_session.assert_awaited_once_with(token_digest=token.digest)
        pending_write.assert_not_awaited()

        accepted = await client.post(
            "/v1/setup/native-identity",
            headers=headers,
            json={"login_handle": "owner@example.test", "password": "valid-owner-password"},
        )
        assert accepted.status_code == 204
        pending_write.assert_awaited_once()
