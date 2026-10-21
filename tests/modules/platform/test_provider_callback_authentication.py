"""Provider-event callback authentication and HTTP boundary (no database).

The oracle re-implements the documented v1 signing contract with hashlib/hmac
directly instead of calling the production signing helpers, so a drift in the
derivation label, field order or signed material makes these tests fail.
"""

import hashlib
import hmac
import json
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from request_engine.entrypoints.http.provider_callbacks import create_provider_callback_router
from request_engine.platform.events.callback_signature import HmacProviderCallbackAuthenticator
from request_engine.platform.events.callbacks import ProviderCallbackAuthenticationFailed

pytestmark = [pytest.mark.unit]

MASTER = b"m" * 32
NOW = 1_800_000_000
CONNECTIONS = frozenset({("webhook", "primary")})
ORG = UUID("0b6d9a52-7a3e-4f1d-8c2b-4e5f6a7b8c9d")


def _oracle_signature(
    master: bytes, org: UUID, provider: str, connection: str, timestamp: int, body: bytes
) -> str:
    material = f"request-engine.provider-callback.v1\n{org}\n{provider}\n{connection}"
    key = hmac.new(master, material.encode(), hashlib.sha256).digest()
    digest = hmac.new(key, b"v1\n" + str(timestamp).encode() + b"\n" + body, hashlib.sha256)
    return "v1=" + digest.hexdigest()


def _headers(
    body: bytes,
    *,
    org: UUID = ORG,
    provider: str = "webhook",
    connection: str = "primary",
    timestamp: int = NOW,
    master: bytes = MASTER,
) -> dict[str, str]:
    return {
        "X-Request-Engine-Organization": str(org),
        "X-Request-Engine-Timestamp": str(timestamp),
        "X-Request-Engine-Signature": _oracle_signature(
            master, org, provider, connection, timestamp, body
        ),
    }


def _request(path: str, headers: dict[str, str], body: bytes) -> Request:
    _, _, _, provider, connection = path.split("/")
    sent = False

    async def receive() -> dict[str, Any]:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    scope: dict[str, Any] = {
        "type": "http",
        "method": "POST",
        "path": path,
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "path_params": {"provider_key": provider, "connection_key": connection},
    }
    return Request(scope, receive)


def _authenticator(**overrides: Any) -> HmacProviderCallbackAuthenticator:
    options: dict[str, Any] = {"connections": CONNECTIONS, "clock": lambda: float(NOW)}
    options.update(overrides)
    return HmacProviderCallbackAuthenticator(MASTER, **options)


BODY = b'{"provider_event_id":"evt-1","payload":{"status":"delivered"}}'
PATH = "/v1/provider-events/webhook/primary"


@pytest.mark.asyncio
async def test_valid_signature_binds_organization_provider_and_connection() -> None:
    trusted = await _authenticator().authenticate_callback(_request(PATH, _headers(BODY), BODY))
    assert (trusted.organization_id, trusted.provider_key, trusted.connection_key) == (
        ORG,
        "webhook",
        "primary",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "headers", "body", "reason"),
    [
        (PATH, _headers(BODY, master=b"x" * 32), BODY, "signature_mismatch"),
        (PATH, _headers(b'{"tampered":true}'), BODY, "signature_mismatch"),
        # Signed for organization A but presented as organization B.
        (
            PATH,
            {**_headers(BODY), "X-Request-Engine-Organization": str(uuid4())},
            BODY,
            "signature_mismatch",
        ),
        # Signed for another connection key and replayed at the registered one.
        (PATH, _headers(BODY, connection="secondary"), BODY, "signature_mismatch"),
        (
            PATH,
            {k: v for k, v in _headers(BODY).items() if "Signature" not in k},
            BODY,
            "signature_missing",
        ),
        (PATH, {}, BODY, "organization_missing_or_invalid"),
        (
            PATH,
            {k: v for k, v in _headers(BODY).items() if "Timestamp" not in k},
            BODY,
            "timestamp_missing_or_invalid",
        ),
        (PATH, _headers(BODY, timestamp=NOW - 301), BODY, "timestamp_outside_window"),
        (PATH, _headers(BODY, timestamp=NOW + 301), BODY, "timestamp_outside_window"),
        (
            "/v1/provider-events/webhook/secondary",
            _headers(BODY, connection="secondary"),
            BODY,
            "unregistered_connection",
        ),
    ],
    ids=[
        "wrong-secret",
        "body-tampered",
        "wrong-organization",
        "wrong-connection",
        "missing-signature",
        "missing-credentials",
        "missing-timestamp",
        "expired",
        "future",
        "unregistered-connection",
    ],
)
async def test_unauthenticated_callbacks_fail_closed(
    path: str, headers: dict[str, str], body: bytes, reason: str
) -> None:
    with pytest.raises(ProviderCallbackAuthenticationFailed) as failure:
        await _authenticator().authenticate_callback(_request(path, headers, body))
    assert failure.value.reason == reason


def test_short_master_secret_and_empty_connections_are_rejected_at_composition() -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        HmacProviderCallbackAuthenticator(b"short", connections=CONNECTIONS)
    with pytest.raises(ValueError, match="connection"):
        HmacProviderCallbackAuthenticator(MASTER, connections=frozenset())


class _UnusableSessionFactory:
    """Any persistence attempt on a rejected callback is itself a defect."""

    def __call__(self) -> object:
        raise AssertionError("a rejected provider callback must not open a database session")


def _client() -> AsyncClient:
    app = FastAPI()
    app.include_router(
        create_provider_callback_router(
            session_factory=_UnusableSessionFactory(),  # type: ignore[arg-type]
            authenticator=_authenticator(),
        )
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_http_rejections_never_reach_persistence() -> None:
    async with _client() as client:
        unauthenticated = await client.post(
            PATH, content=BODY, headers=_headers(BODY, master=b"z" * 32)
        )
        oversized_body = json.dumps({"provider_event_id": "e", "payload": {"x": "y" * 70_000}})
        oversized = await client.post(
            PATH, content=oversized_body, headers=_headers(oversized_body.encode())
        )
        bad_shape = b'{"provider_event_id":"e","payload":{},"organization_id":"x"}'
        malformed = await client.post(PATH, content=bad_shape, headers=_headers(bad_shape))
        unregistered = await client.post(
            "/v1/provider-events/sms/primary",
            content=BODY,
            headers=_headers(BODY, provider="sms"),
        )

    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["error"]["code"] == "provider_callback_authentication_failed"
    assert unregistered.status_code == 401
    assert unregistered.json() == unauthenticated.json()
    assert oversized.status_code == 413
    assert malformed.status_code == 422
    assert malformed.json()["error"]["code"] == "invalid_provider_event"
