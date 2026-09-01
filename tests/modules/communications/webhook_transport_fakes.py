import email.message
import json
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from request_engine.modules.communications.contracts.delivery import (
    ProviderLookupRequest,
    ProviderSendRequest,
)

BASE_URL = "https://transport.example.test/webhook"


class FakeResponse:
    def __init__(self, status: int, body: dict[str, Any]) -> None:
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return json.dumps(self._body).encode("utf-8")


class FakeTransport:
    def __init__(self, outcome: FakeResponse | Exception) -> None:
        self.outcome = outcome
        self.requests: list[urllib.request.Request] = []
        self.timeouts: list[float] = []

    def __call__(self, request: urllib.request.Request, *, timeout: float) -> FakeResponse:
        self.requests.append(request)
        self.timeouts.append(timeout)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(BASE_URL, code, "failure", email.message.Message(), None)


def send_request() -> ProviderSendRequest:
    task_id = uuid4()
    return ProviderSendRequest(
        delivery_id=uuid4(),
        communication_task_id=task_id,
        provider_key="webhook",
        provider_idempotency_key=f"communication:{task_id}:attempt:2",
        channel="email",
        destination="patient@example.test",
        contact_point_id=uuid4(),
        template_key="booking-confirmed",
        template_version=3,
        render_context={"clinic": "Sala 4"},
        expires_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
        reconcile_after_seconds=300,
    )


def lookup_request() -> ProviderLookupRequest:
    task_id = uuid4()
    return ProviderLookupRequest(
        delivery_id=uuid4(),
        communication_task_id=task_id,
        provider_key="webhook",
        provider_idempotency_key=f"communication:{task_id}:attempt:1",
        provider_message_id=None,
    )
