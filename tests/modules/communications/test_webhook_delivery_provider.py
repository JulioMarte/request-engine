from __future__ import annotations

import json
import urllib.error
import urllib.parse
from typing import Any

import pytest
import webhook_transport_fakes as fakes

from request_engine.modules.communications.adapters.transport.webhook_delivery_provider import (
    WebhookDeliveryProvider,
)
from request_engine.modules.communications.contracts.delivery import ProviderDeliveryStatus

pytestmark = [pytest.mark.unit]


@pytest.mark.asyncio
async def test_send_posts_handoff_payload_and_reports_accepted_handoff() -> None:
    transport = fakes.FakeTransport(fakes.FakeResponse(202, {"provider_message_id": "msg-1"}))
    provider = WebhookDeliveryProvider(
        fakes.BASE_URL,
        auth_header=("Authorization", "Bearer token-1"),
        timeout_seconds=5.0,
        transport=transport,
    )
    request = fakes.send_request()

    result = await provider.send(request)

    assert result.status is ProviderDeliveryStatus.ACCEPTED
    assert result.provider_message_id == "msg-1"
    assert result.retryable is False
    assert transport.timeouts == [5.0]
    http_request = transport.requests[0]
    assert http_request.get_method() == "POST"
    assert http_request.full_url == fakes.BASE_URL
    assert http_request.get_header("Authorization") == "Bearer token-1"
    raw_payload = http_request.data
    assert isinstance(raw_payload, bytes)
    assert json.loads(raw_payload) == {
        "delivery_id": str(request.delivery_id),
        "communication_task_id": str(request.communication_task_id),
        "dedupe_key": request.provider_idempotency_key,
        "attempt_no": 2,
        "provider_key": "webhook",
        "channel": "email",
        "recipient": {
            "contact_point_id": str(request.contact_point_id),
            "destination": "patient@example.test",
        },
        "content": {
            "template_key": "booking-confirmed",
            "template_version": 3,
            "render_context": {"clinic": "Sala 4"},
        },
        "expires_at": "2026-09-01T12:00:00+00:00",
        "reconcile_after_seconds": 300,
    }


@pytest.mark.asyncio
async def test_send_non_2xx_maps_to_retryable_failure() -> None:
    transport = fakes.FakeTransport(fakes.http_error(503))
    provider = WebhookDeliveryProvider(fakes.BASE_URL, transport=transport)

    result = await provider.send(fakes.send_request())

    assert result.status is ProviderDeliveryStatus.FAILED
    assert result.retryable is True
    assert result.result_data["http_status"] == 503


@pytest.mark.asyncio
async def test_send_transport_exception_propagates_for_worker_ambiguous_classification() -> None:
    transport = fakes.FakeTransport(TimeoutError("connect timed out"))
    provider = WebhookDeliveryProvider(fakes.BASE_URL, transport=transport)

    with pytest.raises(TimeoutError):
        await provider.send(fakes.send_request())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"status": "delivered", "provider_message_id": "m-1"}, "delivered"),
        ({"status": "failed"}, "failed"),
        ({"status": "not_found"}, "ambiguous"),
        ({"status": "unknown"}, "ambiguous"),
        ({"status": "pending"}, "ambiguous"),
        ({}, "ambiguous"),
    ],
)
async def test_lookup_maps_remote_status_without_inventing_terminal_outcomes(
    body: dict[str, Any],
    expected: str,
) -> None:
    transport = fakes.FakeTransport(fakes.FakeResponse(200, body))
    provider = WebhookDeliveryProvider(fakes.BASE_URL, transport=transport)

    result = await provider.lookup(fakes.lookup_request())

    assert result.status == expected
    if expected == "ambiguous":
        assert result.status is not ProviderDeliveryStatus.DELIVERED
        assert result.status is not ProviderDeliveryStatus.FAILED
        assert result.retryable is False


@pytest.mark.asyncio
async def test_lookup_gets_quoted_identity_and_maps_http_404_to_ambiguous() -> None:
    transport = fakes.FakeTransport(fakes.http_error(404))
    provider = WebhookDeliveryProvider(fakes.BASE_URL, transport=transport)
    request = fakes.lookup_request()

    result = await provider.lookup(request)

    identity = urllib.parse.quote(request.provider_idempotency_key, safe="")
    assert transport.requests[0].get_method() == "GET"
    assert transport.requests[0].full_url == f"{fakes.BASE_URL}/status/{identity}"
    assert result.status is ProviderDeliveryStatus.AMBIGUOUS
    assert result.status is not ProviderDeliveryStatus.FAILED
    assert result.status is not ProviderDeliveryStatus.NOT_FOUND
    assert result.retryable is False
    assert result.provider_message_id is None


@pytest.mark.asyncio
async def test_lookup_infrastructure_failure_propagates_for_lookup_retry() -> None:
    transport = fakes.FakeTransport(fakes.http_error(503))
    provider = WebhookDeliveryProvider(fakes.BASE_URL, transport=transport)

    with pytest.raises(urllib.error.HTTPError):
        await provider.lookup(fakes.lookup_request())
