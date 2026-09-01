import asyncio
import json
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Protocol, cast
from urllib.parse import quote

from request_engine.modules.communications.contracts.delivery import (
    ProviderDeliveryResult,
    ProviderDeliveryStatus,
    ProviderLookupRequest,
    ProviderSendRequest,
)

WEBHOOK_PROVIDER_KEY = "webhook"

_LOOKUP_REMOTE_STATUSES = {
    "delivered": ProviderDeliveryStatus.DELIVERED,
    "failed": ProviderDeliveryStatus.FAILED,
}


class _HttpResponse(Protocol):
    status: int

    def read(self) -> bytes: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    # A 3xx must never be followed: urllib would replay the auth header to the
    # Location target, including on an https -> http downgrade.
    def redirect_request(
        self, req: object, fp: object, code: object, msg: object, headers: object, newurl: object
    ) -> None:
        return None


_OPENER = urllib.request.build_opener(_NoRedirect())


class WebhookDeliveryProvider:
    """F7a remote delivery transport over a configured HTTPS webhook."""

    def __init__(
        self,
        base_url: str,
        *,
        auth_header: tuple[str, str] | None = None,
        timeout_seconds: float = 10.0,
        transport: Callable[..., _HttpResponse] | None = None,
    ) -> None:
        if not base_url.startswith("https://"):
            raise ValueError("webhook base_url must be an https URL")
        self._base_url = base_url.rstrip("/")
        self._auth_header = auth_header
        self._timeout_seconds = timeout_seconds
        self._transport = transport if transport is not None else _OPENER.open

    async def send(self, request: ProviderSendRequest) -> ProviderDeliveryResult:
        payload = json.dumps(_handoff_payload(request), default=str).encode("utf-8")
        try:
            req = self._request(self._base_url, payload)
            response = await asyncio.to_thread(self._transport, req, timeout=self._timeout_seconds)
        except urllib.error.HTTPError as exc:
            return ProviderDeliveryResult(
                status=ProviderDeliveryStatus.FAILED,
                retryable=True,
                result_data={"error_phase": "send", "http_status": exc.code},
            )
        body = _json_body(response)
        return ProviderDeliveryResult(
            status=ProviderDeliveryStatus.ACCEPTED,
            provider_message_id=_message_id(body),
            result_data={"http_status": response.status},
        )

    async def lookup(self, request: ProviderLookupRequest) -> ProviderDeliveryResult:
        identity = quote(request.provider_idempotency_key, safe="")
        try:
            req = self._request(f"{self._base_url}/status/{identity}")
            response = await asyncio.to_thread(self._transport, req, timeout=self._timeout_seconds)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return _lookup_result(ProviderDeliveryStatus.AMBIGUOUS, None, "http_404")
            raise
        body = _json_body(response)
        remote = str(body.get("status", ""))
        status = _LOOKUP_REMOTE_STATUSES.get(remote, ProviderDeliveryStatus.AMBIGUOUS)
        return _lookup_result(status, _message_id(body), remote or "unknown")

    def _request(self, url: str, payload: bytes | None = None) -> urllib.request.Request:
        headers: dict[str, str] = {"Content-Type": "application/json"} if payload else {}
        if self._auth_header is not None:
            headers[self._auth_header[0]] = self._auth_header[1]
        return urllib.request.Request(url, data=payload, headers=headers)


def _handoff_payload(request: ProviderSendRequest) -> dict[str, object]:
    return {
        "delivery_id": str(request.delivery_id),
        "communication_task_id": str(request.communication_task_id),
        "dedupe_key": request.provider_idempotency_key,
        "attempt_no": request.attempt_no,
        "provider_key": request.provider_key,
        "channel": request.channel,
        "recipient": {
            "contact_point_id": str(request.contact_point_id),
            "destination": request.destination,
        },
        "content": {
            "template_key": request.template_key,
            "template_version": request.template_version,
            "render_context": request.render_context,
        },
        "expires_at": (request.expires_at.isoformat() if request.expires_at is not None else None),
        "reconcile_after_seconds": request.reconcile_after_seconds,
    }


def _json_body(response: _HttpResponse) -> dict[str, object]:
    try:
        parsed: object = json.loads(response.read())
    except ValueError:
        return {}
    return cast("dict[str, object]", parsed) if isinstance(parsed, dict) else {}


def _message_id(body: dict[str, object]) -> str | None:
    value = body.get("provider_message_id")
    return value if isinstance(value, str) else None


def _lookup_result(
    status: ProviderDeliveryStatus,
    provider_message_id: str | None,
    remote_status: str,
) -> ProviderDeliveryResult:
    return ProviderDeliveryResult(
        status=status,
        provider_message_id=provider_message_id,
        result_data={"remote_status": remote_status},
    )
