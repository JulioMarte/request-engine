# pyright: reportPrivateUsage=false
from __future__ import annotations

import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar

import pytest
import webhook_transport_fakes as fakes

from request_engine.modules.communications.adapters.transport.webhook_delivery_provider import (
    _OPENER,
    WebhookDeliveryProvider,
)
from request_engine.modules.communications.contracts.delivery import ProviderDeliveryStatus

pytestmark = [pytest.mark.unit, pytest.mark.invariant]

AUTH = ("Authorization", "Bearer secret-token")


@pytest.mark.asyncio
async def test_send_302_is_retryable_failure_with_exactly_one_request() -> None:
    transport = fakes.FakeTransport(fakes.http_error(302))
    provider = WebhookDeliveryProvider(fakes.BASE_URL, auth_header=AUTH, transport=transport)

    result = await provider.send(fakes.send_request())

    assert result.status is ProviderDeliveryStatus.FAILED
    assert result.retryable is True
    assert result.result_data["http_status"] == 302
    assert len(transport.requests) == 1
    sent = transport.requests[0]
    assert sent.get_method() == "POST"
    assert sent.full_url == fakes.BASE_URL
    assert sent.get_header("Authorization") == "Bearer secret-token"


@pytest.mark.asyncio
async def test_lookup_302_propagates_http_error_without_following_redirect() -> None:
    transport = fakes.FakeTransport(fakes.http_error(302))
    provider = WebhookDeliveryProvider(fakes.BASE_URL, auth_header=AUTH, transport=transport)
    request = fakes.lookup_request()
    identity = urllib.parse.quote(request.provider_idempotency_key, safe="")

    with pytest.raises(urllib.error.HTTPError) as raised:
        await provider.lookup(request)

    assert raised.value.code == 302
    assert len(transport.requests) == 1
    sent = transport.requests[0]
    assert sent.get_method() == "GET"
    assert sent.full_url == f"{fakes.BASE_URL}/status/{identity}"
    assert sent.get_header("Authorization") == "Bearer secret-token"


def test_provider_default_transport_is_the_redirect_refusing_opener() -> None:
    provider = WebhookDeliveryProvider(fakes.BASE_URL)

    assert provider._transport == _OPENER.open
    assert provider._transport != urllib.request.urlopen


class _RedirectServerHandler(BaseHTTPRequestHandler):
    hits: ClassVar[list[tuple[str, str]]] = []
    location: ClassVar[str] = ""

    def _respond(self) -> None:
        _RedirectServerHandler.hits.append((self.command, self.path))
        self.send_response(302)
        self.send_header("Location", _RedirectServerHandler.location)
        self.end_headers()

    do_GET = _respond
    do_POST = _respond

    def log_message(self, format: str, *args: object) -> None:
        return None


@pytest.fixture
def redirect_server() -> Iterator[tuple[str, list[tuple[str, str]]]]:
    hits: list[tuple[str, str]] = []
    _RedirectServerHandler.hits = hits
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RedirectServerHandler)
    _RedirectServerHandler.location = (
        f"http://127.0.0.1:{server.server_address[1]}/cleartext-target"
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield (f"http://127.0.0.1:{server.server_address[1]}", hits)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("data", [b'{"attempt": 1}', None])
def test_real_opener_refuses_302_for_post_and_get_keeping_single_request(
    redirect_server: tuple[str, list[tuple[str, str]]],
    data: bytes | None,
) -> None:
    base_url, hits = redirect_server
    request = urllib.request.Request(f"{base_url}/source", data=data)

    with pytest.raises(urllib.error.HTTPError) as raised:
        _OPENER.open(request, timeout=5)

    assert raised.value.code == 302
    assert hits == [("POST" if data is not None else "GET", "/source")]
